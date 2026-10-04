namespace ArbScanner.Learning;

public record TutorialCard(string Glyph, string Title, string Body);

/// <summary>"What this screen is for" + "what to do here".</summary>
public record ScreenIntro(string Key, string Title, string Purpose, string WhatToDo);

/// <summary>Help shown under one setting: what it does, which way to turn it, and a starting value.</summary>
public record SettingHelp(string Key, string WhatItDoes, string RaiseLower, string Suggested, string Term);

public static class HelpText
{
    public static readonly IReadOnlyList<TutorialCard> Tutorial = new List<TutorialCard>
    {
        new("⇄", "What arbitrage is",
            "Every market here is a yes/no question, and the winning side pays $1 per contract.\n\nIf Kalshi sells YES for 45¢ and Polymarket US sells NO on the same question for 52¢, you can buy both for 97¢. One of them must win, so you get $1 back: 3¢ profit no matter what happens.\n\nThis app hunts for those moments."),
        new("⚠︎", "Why it isn't free money",
            "• Fees: each side costs up to ~1.75¢ per contract, so small gaps vanish.\n• Different rules: if the exchanges settle the 'same' question differently, both sides can lose.\n• Prices move: you place two separate orders, and the second price can change before you finish.\n• Thin books: only a few contracts may be available at the good price.\n\nThe app checks the math. You check that the bets really match."),
        new("◉", "How the scanner works",
            "1. Discovery (every 30 min): reads every open market on both exchanges and suggests look-alike pairs.\n2. You review: approve the real matches, reject the rest.\n3. Watching (every ~30 s): checks both order books for approved pairs.\n4. Alert: when buying both sides costs less than $1 after fees by your minimum edge, you get a push.\n5. Paper trade: it records what you would have bought and scores it when the markets settle."),
        new("✓", "Your job: Review",
            "The Review tab lists suggested pairs. For each one:\n\n• Same: Kalshi YES and Polymarket YES are the same outcome.\n• Inverse: Kalshi YES is Polymarket's NO (e.g. each names a different team).\n• Rules: compare how each exchange settles it.\n• Reject: not the same bet.\n\nOnly approved pairs get watched. When unsure, reject. A missed arb costs nothing; a bad pair can cost both sides."),
        new("$", "Reading an opportunity",
            "• Edge: profit per contract after fees. Under 2¢ is fragile.\n• Profit: dollars for the full size.\n• Return: profit ÷ money spent.\n• Annualized: that return scaled to a year, so a quick 2% beats a slow 2%.\n• Contracts: how many you could buy at these prices.\n\nTap any opportunity for a step-by-step walkthrough of the exact trade and its risks."),
        new("▤", "Paper trading first",
            "Every opportunity opens a simulated position. When the markets settle, the Paper tab shows what you would have made.\n\nWatch for divergent resolutions: pairs where the exchanges disagreed and both sides lost. Zero divergences across many settled trades is the evidence you want before using real money."),
        new("?", "Help is always here",
            "Learning mode is on: every screen has an intro card, ⓘ buttons explain each number, and every pair and opportunity has an Explain walkthrough.\n\nTurn it off with the ? button on any tab, or in Settings. Replay this tutorial or browse the glossary from Settings any time."),
    };

    public static readonly IReadOnlyDictionary<string, ScreenIntro> Screens = new Dictionary<string, ScreenIntro>
    {
        ["dashboard"] = new("dashboard", "Your scanner at a glance",
            "Shows whether the scanner is running, how many live opportunities and pairs it's watching, what's waiting for review, and your paper-trading results.",
            "Start with 'To review': the scanner only watches pairs you approve. Once pairs are approved, check back here or wait for a push."),
        ["opportunities"] = new("opportunities", "Live arbitrage opportunities",
            "Each card is an approved pair where buying both sides currently costs less than $1 after fees, by at least your minimum edge. 'Live only' off shows past ones too.",
            "Tap a card for the full walkthrough: exact trade, profit math, verdict, and risks. Opportunities often last seconds to minutes, so act or move on."),
        ["review"] = new("review", "Review suggested pairs",
            "The matcher found markets on both exchanges that look like the same question. Each pair has a 1–10 deal rating (match confidence × profit after fees), and the best are listed first.",
            "Use the quick filters (8+, gap now, closing soon) or Filters to cut the list down, search for a team or topic, then tap Explain on a card and choose Same, Inverse or Reject. Reject anything you're unsure about."),
        ["pairs"] = new("pairs", "Pairs you approved",
            "These are the pairs the scanner checks every cycle.",
            "Tap a pair to pause it, flip Same/Inverse, remove it, or re-read the rules. Remove any pair that ever resolved divergently."),
        ["paper"] = new("paper", "Paper trading results",
            "Simulated positions opened at the exact prices of each opportunity, scored when both markets settle.",
            "Use this to build trust before risking money. Watch the divergent count: any non-zero value means a pair wasn't really the same bet."),
        ["settings"] = new("settings", "Tune the scanner",
            "Thresholds decide what counts as an opportunity; alert settings decide when you're notified; matching settings decide what gets suggested for review.",
            "Defaults are reasonable for learning. Raise Min edge to about 2–3¢ and set Min annualized once you're comfortable."),
        ["opportunity"] = new("opportunity", "One opportunity, step by step",
            "The exact two orders, what they cost with fees, why one side must pay $1, and the profit that leaves.",
            "Read the verdict and risks, then check both exchanges' rules with the buttons below. In this app it's paper only."),
    };

    public static readonly IReadOnlyDictionary<string, SettingHelp> Settings = new Dictionary<string, SettingHelp>
    {
        ["scan_enabled"] = new("scan_enabled", "Turns price watching and alerts on or off. Discovery keeps finding new suggestions either way.",
            "Off pauses everything except discovery.", "On", "arbitrage"),
        ["min_edge_cents"] = new("min_edge_cents", "The smallest profit per contract, after fees, that counts as an opportunity.",
            "Higher = fewer but safer alerts. Lower = more alerts that a small price move can erase.", "Start at 1¢ to learn, then use 2–3¢.", "min-edge"),
        ["min_profit_dollars"] = new("min_profit_dollars", "The smallest total profit for the whole size.",
            "Higher = only bigger opportunities. Lower = includes tiny ones that aren't worth two orders.", "$1 to learn, then $5+.", "min-profit"),
        ["min_annualized"] = new("min_annualized", "The smallest yearly-equivalent return (%). 0 = off.",
            "Higher = skips slow markets that lock your money for months.", "0 to learn, then 10–20%.", "min-annualized"),
        ["paper_max_stake"] = new("paper_max_stake", "The most the paper trader spends (both sides) per opportunity.",
            "Set it near what you'd really risk, so paper results are realistic.", "$500", "stake"),
        ["alert_cooldown_min"] = new("alert_cooldown_min", "Minutes before the same pair can alert again.",
            "Higher = fewer repeat pings for a flickering arb.", "30 minutes", "cooldown"),
        ["quiet_hours"] = new("quiet_hours", "No pushes between these hours (server time). Opportunities are still recorded.",
            "Leave blank to always notify.", "23 → 7", "quiet-hours"),
        ["match_min_score"] = new("match_min_score", "How similar two markets' wording must be to be suggested (0–100).",
            "Higher = fewer, cleaner suggestions. Lower = more pairs, more junk to reject.", "82", "match-settings"),
        ["match_date_window_days"] = new("match_date_window_days", "How many days apart two markets' dates can be.",
            "Smaller = fewer mismatched 'next week' pairs. Larger catches long-dated futures with different deadlines.", "7 days", "match-settings"),
    };
}
