//! Aftershock's notebook on NEAR testnet.
//!
//! It stores three things: the fingerprint of the data snapshot, the counts of a run, and forecasts with due dates.
//! What the chain enforces: only the owner records runs and forecasts; a forecast cannot be changed after it is
//! posted; nobody can settle a forecast before its due date; every settlement carries the settler's account,
//! the block time and the fingerprint of the data it was computed from.
//! What it cannot do: see mainnet data or check a forecast itself. It is a timestamped notebook, not a referee.

use near_sdk::{env, near, AccountId, PanicOnDefault};

const DAY_NS: u64 = 86_400_000_000_000;
const MAX_TEXT: usize = 400;

#[near(serializers = [borsh, json])]
#[derive(Clone)]
pub struct Run {
    pub fingerprint: String,
    pub cutoff: String,
    pub events: u32,
    pub moved_price: u32,
    pub moved_usage: u32,
    pub claims_written: u32,
    pub claims_kept: u32,
    pub ai_alone_right: u32,
    pub ai_alone_wrong: u32,
    pub ai_alone_uncheckable: u32,
    pub recorded_at_ns: u64,
}

#[near(serializers = [borsh, json])]
#[derive(Clone)]
pub struct Settlement {
    pub settler: AccountId,
    pub by_owner: bool,
    pub outcome: bool,
    pub observed: String,
    pub fingerprint: String,
    pub settled_at_ns: u64,
}

#[near(serializers = [borsh, json])]
#[derive(Clone)]
pub struct Forecast {
    pub id: u32,
    pub run: u32,
    pub side: String,
    pub statement: String,
    pub measure: String,
    pub direction: String,
    pub threshold: String,
    /// Days since 1970-01-01 (UTC) of the due date. Settling is refused until the day after.
    pub due_day: u32,
    pub posted_at_ns: u64,
    pub settlements: Vec<Settlement>,
}

#[near(contract_state)]
#[derive(PanicOnDefault)]
pub struct Notebook {
    owner: AccountId,
    runs: Vec<Run>,
    forecasts: Vec<Forecast>,
}

fn check_hash(h: &str) {
    assert!(h.len() == 64 && h.bytes().all(|b| b.is_ascii_hexdigit()), "fingerprint must be 64 hex characters");
}

#[near]
impl Notebook {
    #[init]
    pub fn new(owner: AccountId) -> Self {
        Self { owner, runs: Vec::new(), forecasts: Vec::new() }
    }

    /// Owner only: record a run's snapshot fingerprint and counts. Returns the run's number.
    #[allow(clippy::too_many_arguments)]
    pub fn record_run(&mut self, fingerprint: String, cutoff: String, events: u32, moved_price: u32, moved_usage: u32,
                      claims_written: u32, claims_kept: u32, ai_alone_right: u32, ai_alone_wrong: u32, ai_alone_uncheckable: u32) -> u32 {
        assert_eq!(env::predecessor_account_id(), self.owner, "only the owner records runs");
        check_hash(&fingerprint);
        assert!(cutoff.len() == 10, "cutoff must be YYYY-MM-DD");
        self.runs.push(Run { fingerprint, cutoff, events, moved_price, moved_usage, claims_written, claims_kept,
                             ai_alone_right, ai_alone_wrong, ai_alone_uncheckable, recorded_at_ns: env::block_timestamp() });
        (self.runs.len() - 1) as u32
    }

    /// Owner only: post a forecast. It cannot be edited or deleted afterwards. Returns its id.
    pub fn post_forecast(&mut self, run: u32, side: String, statement: String, measure: String, direction: String,
                         threshold: String, due_day: u32) -> u32 {
        assert_eq!(env::predecessor_account_id(), self.owner, "only the owner posts forecasts");
        assert!((run as usize) < self.runs.len(), "unknown run");
        assert!(direction == "above" || direction == "below", "direction must be above or below");
        assert!(!statement.is_empty() && statement.len() <= MAX_TEXT, "statement must be 1 to 400 bytes");
        assert!(side.len() <= 16 && measure.len() <= 32 && threshold.len() <= 32, "field too long");
        let id = self.forecasts.len() as u32;
        self.forecasts.push(Forecast { id, run, side, statement, measure, direction, threshold, due_day,
                                       posted_at_ns: env::block_timestamp(), settlements: Vec::new() });
        id
    }

    /// Anyone: record what the data showed, but only after the due date has passed (by the chain's own clock).
    /// Each account may settle a forecast once. The settler's account and the data fingerprint are stored with it.
    pub fn settle(&mut self, id: u32, outcome: bool, observed: String, fingerprint: String) {
        check_hash(&fingerprint);
        assert!(observed.len() <= 32, "observed too long");
        let now = env::block_timestamp();
        let who = env::predecessor_account_id();
        let by_owner = who == self.owner;
        let f = self.forecasts.get_mut(id as usize).expect("unknown forecast");
        assert!(now >= (f.due_day as u64 + 1) * DAY_NS, "too early: the due date has not passed");
        assert!(f.settlements.iter().all(|s| s.settler != who), "this account already settled this forecast");
        assert!(f.settlements.len() < 20, "settlement list is full");
        f.settlements.push(Settlement { settler: who, by_owner, outcome, observed, fingerprint, settled_at_ns: now });
    }

    pub fn get_owner(&self) -> AccountId {
        self.owner.clone()
    }

    pub fn get_runs(&self) -> Vec<Run> {
        self.runs.clone()
    }

    pub fn get_forecasts(&self) -> Vec<Forecast> {
        self.forecasts.clone()
    }

    pub fn get_forecast(&self, id: u32) -> Option<Forecast> {
        self.forecasts.get(id as usize).cloned()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use near_sdk::test_utils::VMContextBuilder;
    use near_sdk::testing_env;

    const H: &str = "2a4b74320b84e0ad81a8472a0536ec476d814356bd6b6a0a5be09e604fa871ad";

    fn ctx(who: &str, day: u64) {
        let mut b = VMContextBuilder::new();
        b.predecessor_account_id(who.parse().unwrap()).block_timestamp(day * DAY_NS + 1);
        testing_env!(b.build());
    }

    fn setup() -> Notebook {
        ctx("owner.testnet", 100);
        let mut n = Notebook::new("owner.testnet".parse().unwrap());
        assert_eq!(n.record_run(H.into(), "2026-11-11".into(), 74, 8, 10, 20, 9, 1, 5, 4), 0);
        assert_eq!(n.post_forecast(0, "bull".into(), "Price above 3".into(), "price".into(), "above".into(), "3".into(), 110), 0);
        n
    }

    #[test]
    fn records_and_reads() {
        let n = setup();
        assert_eq!(n.get_runs()[0].fingerprint, H);
        assert_eq!(n.get_forecasts()[0].due_day, 110);
    }

    #[test]
    #[should_panic(expected = "too early")]
    fn cannot_settle_before_due() {
        let mut n = setup();
        ctx("owner.testnet", 110);
        n.settle(0, true, "3.5".into(), H.into());
    }

    #[test]
    fn anyone_settles_after_due_once() {
        let mut n = setup();
        ctx("stranger.testnet", 111);
        n.settle(0, false, "2.9".into(), H.into());
        ctx("owner.testnet", 112);
        n.settle(0, true, "3.5".into(), H.into());
        let f = n.get_forecast(0).unwrap();
        assert_eq!(f.settlements.len(), 2);
        assert!(!f.settlements[0].by_owner && f.settlements[1].by_owner);
    }

    #[test]
    #[should_panic(expected = "already settled")]
    fn no_double_settle() {
        let mut n = setup();
        ctx("owner.testnet", 111);
        n.settle(0, true, "3.5".into(), H.into());
        n.settle(0, false, "1".into(), H.into());
    }

    #[test]
    #[should_panic(expected = "only the owner")]
    fn stranger_cannot_post() {
        let mut n = setup();
        ctx("stranger.testnet", 101);
        n.post_forecast(0, "bear".into(), "x".into(), "price".into(), "below".into(), "1".into(), 120);
    }

    #[test]
    #[should_panic(expected = "64 hex")]
    fn bad_fingerprint() {
        let mut n = setup();
        n.record_run("nope".into(), "2026-11-11".into(), 1, 1, 1, 1, 1, 1, 1, 1);
    }
}
