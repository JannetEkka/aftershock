// Testnet-only scripts for Aftershock's notebook contract. Never mainnet: the network id is fixed below.
//   node chain.mjs create        make a fresh testnet account from the faucet, save its key OUTSIDE the repo
//   node chain.mjs deploy        deploy the contract and initialise it
//   node chain.mjs record        record the run's counts and post its forecasts (reads ../results.json)
//   node chain.mjs settle        settle every forecast whose due date has passed (reads ../settle.json)
//   node chain.mjs view          print what the contract holds (no key needed)
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import nearAPI from "near-api-js";

const { connect, keyStores, KeyPair } = nearAPI;
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const NETWORK = "testnet";
const RPC = process.env.NEAR_RPC || "https://rpc.testnet.near.org";
const HELPER = "https://helper.testnet.near.org";
const EXPLORER = "https://testnet.nearblocks.io";
const KEY_FILE = process.env.AFTERSHOCK_KEY_FILE || path.join(os.homedir(), ".aftershock", "testnet-key.json");
const ONCHAIN = path.join(HERE, "onchain.json");
const GAS = "60000000000000";

const readJson = (p, d) => (fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, "utf8")) : d);
const writeJson = (p, o) => fs.writeFileSync(p, JSON.stringify(o, null, 1) + "\n");
const dayNumber = (iso) => Math.round(Date.parse(iso + "T00:00:00Z") / 86400000);

async function near(withKey) {
  const keyStore = new keyStores.InMemoryKeyStore();
  let accountId = readJson(ONCHAIN, {}).contract;
  if (withKey) {
    if (!fs.existsSync(KEY_FILE)) throw new Error(`no key file at ${KEY_FILE}; run "node chain.mjs create" first`);
    const k = JSON.parse(fs.readFileSync(KEY_FILE, "utf8"));
    accountId = k.account_id;
    await keyStore.setKey(NETWORK, accountId, KeyPair.fromString(k.private_key));
  }
  const conn = await connect({ networkId: NETWORK, nodeUrl: RPC, helperUrl: HELPER, keyStore });
  return { conn, accountId, account: await conn.account(accountId) };
}

const txLink = (h) => `${EXPLORER}/txns/${h}`;
async function call(account, methodName, args) {
  const r = await account.functionCall({ contractId: account.accountId, methodName, args, gas: GAS });
  const v = r.status.SuccessValue ? JSON.parse(Buffer.from(r.status.SuccessValue, "base64").toString() || "null") : null;
  return { hash: r.transaction.hash, value: v };
}

const cmds = {
  async create() {
    if (fs.existsSync(KEY_FILE)) throw new Error(`key file already exists at ${KEY_FILE}`);
    const accountId = `aftershock-${Date.now().toString(36)}.testnet`;
    const kp = KeyPair.fromRandom("ed25519");
    const conn = await connect({ networkId: NETWORK, nodeUrl: RPC, helperUrl: HELPER, keyStore: new keyStores.InMemoryKeyStore() });
    await conn.createAccount(accountId, kp.getPublicKey());
    fs.mkdirSync(path.dirname(KEY_FILE), { recursive: true });
    fs.writeFileSync(KEY_FILE, JSON.stringify({ account_id: accountId, public_key: kp.getPublicKey().toString(), private_key: kp.toString() }), { mode: 0o600 });
    console.log(`created ${accountId}; key saved to ${KEY_FILE} (not in the repo)`);
  },

  async deploy() {
    const { account, accountId } = await near(true);
    const wasm = fs.readFileSync(path.join(ROOT, "contract", "target", "wasm32-unknown-unknown", "release", "aftershock.wasm"));
    const d = await account.deployContract(wasm);
    console.log("deployed", txLink(d.transaction.hash));
    const init = await call(account, "new", { owner: accountId });
    writeJson(ONCHAIN, { network: NETWORK, contract: accountId, explorer: `${EXPLORER}/address/${accountId}`,
      deploy_tx: txLink(d.transaction.hash), init_tx: txLink(init.hash), runs: [], forecasts: [], settlements: [] });
    console.log("initialised", txLink(init.hash));
  },

  async record() {
    const { account } = await near(true);
    const res = readJson(path.join(ROOT, "results.json"));
    const on = readJson(ONCHAIN);
    const c = res.counts;
    const run = await call(account, "record_run", { fingerprint: res.snapshot.fingerprint, cutoff: res.snapshot.cutoff, events: c.events,
      moved_price: c.moved_price, moved_usage: c.moved_usage, claims_written: c.claims_written, claims_kept: c.claims_kept,
      ai_alone_right: c.ai_alone_right, ai_alone_wrong: c.ai_alone_wrong, ai_alone_uncheckable: c.ai_alone_uncheckable });
    on.runs.push({ run: run.value, fingerprint: res.snapshot.fingerprint, cutoff: res.snapshot.cutoff, tx: txLink(run.hash) });
    console.log("run", run.value, txLink(run.hash));
    const post = async (f, local) => {
      const r = await call(account, "post_forecast", { run: run.value, side: f.side, statement: f.statement, measure: f.measure,
        direction: f.direction, threshold: String(f.threshold), due_day: dayNumber(f.due) });
      on.forecasts.push({ id: r.value, local, run: run.value, side: f.side, statement: f.statement, measure: f.measure,
        direction: f.direction, threshold: f.threshold, due: f.due, tx: txLink(r.hash) });
      console.log("forecast", r.value, f.statement, txLink(r.hash));
    };
    for (const f of res.forecasts.filter((x) => x.status === "accepted")) await post(f, f.id);
    if (process.argv.includes("--with-test")) {
      // One forecast whose due date is already past, clearly marked as a test, so `make settle` can be shown working today.
      const last = res.forecasts.find((x) => x.status === "accepted" && x.measure === "price") || { latest: 1 };
      const due = new Date(Date.parse(res.snapshot.cutoff + "T00:00:00Z") - 86400000).toISOString().slice(0, 10);
      await post({ side: "test", measure: "price", direction: "above", threshold: 1, due,
        statement: `TEST of the settle step, not a real forecast: mean daily price over the 7 days ending ${due} will be above 1.` }, "TEST");
    }
    writeJson(ONCHAIN, on);
  },

  async settle() {
    const { account, accountId } = await near(true);
    const on = readJson(ONCHAIN);
    const plan = readJson(path.join(ROOT, "settle.json"), null);
    if (!plan) throw new Error("no settle.json; run `python -m aftershock.settle` first (make settle does both)");
    for (const s of plan.settlements) {
      if (on.settlements.some((x) => x.id === s.id && x.settler === accountId)) { console.log("forecast", s.id, "already settled by this account"); continue; }
      const r = await call(account, "settle", { id: s.id, outcome: s.outcome, observed: String(s.observed), fingerprint: plan.fingerprint });
      on.settlements.push({ id: s.id, settler: accountId, outcome: s.outcome, observed: s.observed, fingerprint: plan.fingerprint, tx: txLink(r.hash) });
      console.log("settled forecast", s.id, s.outcome ? "TRUE" : "FALSE", "observed", s.observed, txLink(r.hash));
    }
    for (const s of plan.not_due) console.log("forecast", s.id, "is not due until after", s.due, "- the contract would refuse it");
    writeJson(ONCHAIN, on);
  },

  async view() {
    const { account, accountId } = await near(false);
    if (!accountId) throw new Error("chain/onchain.json has no contract yet");
    for (const m of ["get_owner", "get_runs", "get_forecasts"]) {
      console.log(m, JSON.stringify(await account.viewFunction({ contractId: accountId, methodName: m, args: {} }), null, 1));
    }
  },
};

const cmd = cmds[process.argv[2]];
if (!cmd) { console.error("usage: node chain.mjs create|deploy|record|settle|view"); process.exit(2); }
cmd().catch((e) => { console.error("FAILED:", e.message || e); process.exit(1); });
