using ArbScanner.Models;

namespace ArbScanner.Learning;

/// <summary>
/// Turns server data into plain-English teaching walkthroughs. Pure functions: everything is computed from the
/// numbers the server sent, so the explanation always matches what the app shows.
/// </summary>
public static class Explainer
{
    // Fee rates per contract (before rounding). Mirrors server/arb/fees.py.
    public const double KalshiFeeRate = 0.07;
    public const double PmusFeeRate = 0.0695;

    public static double FeePerContract(double rate, double price) => rate * price * (1 - price);

    static string C(double dollars) => $"{dollars * 100:0.#}¢";
    static string D(double dollars) => $"${dollars:N2}";
    static string Side(string s) => s.ToUpperInvariant();
    static string Q(string? s) => $"“{s}”";

    static string Duration(double? days) => days switch
    {
        null => "an unknown time",
        < 1d / 24 => "under an hour",
        < 1 => $"about {Math.Max(1, (int)Math.Round(days.Value * 24))} hours",
        < 2 => "about a day",
        _ => $"about {Math.Round(days.Value):0} days",
    };

    // =========================================================================================== candidates

    /// <summary>Best hedged top-of-book combination for a candidate in its suggested orientation.</summary>
    public static (string kSide, string pSide, double cost, double fees)? BestCombo(Candidate c)
    {
        var k = c.Kalshi;
        var p = c.Pmus;
        if (k is null || p is null) return null;
        var combos = c.Inverted
            ? new[] { ("yes", "yes", k.YesAsk, p.YesAsk), ("no", "no", k.NoAsk, p.NoAsk) }
            : new[] { ("yes", "no", k.YesAsk, p.NoAsk), ("no", "yes", k.NoAsk, p.YesAsk) };
        (string, string, double, double)? best = null;
        foreach (var (ks, ps, ka, pa) in combos)
        {
            if (ka is not (> 0 and < 1) || pa is not (> 0 and < 1)) continue;
            var cost = ka.Value + pa.Value;
            var fees = FeePerContract(KalshiFeeRate, ka.Value) + FeePerContract(PmusFeeRate, pa.Value);
            if (best is null || cost + fees < best.Value.Item3 + best.Value.Item4) best = (ks, ps, cost, fees);
        }
        return best;
    }

    public static Explanation ExplainCandidate(Candidate c, ScannerSettings s)
    {
        var k = c.Kalshi;
        var p = c.Pmus;
        var d = c.MatchDetails ?? new MatchDetails();
        var sections = new List<ExplanationSection>();

        // 1. What each market asks
        sections.Add(new("What each market asks", new[]
        {
            $"Kalshi: {Q(k?.Display)}. YES pays $1 if that happens. Now: YES {Cents(k?.YesAsk)}, NO {Cents(k?.NoAsk)}. Closes {k?.CloseDisplay}.",
            $"Polymarket US: {Q(p?.Display)}. {PmusYesMeaning(p, d)} Now: YES {Cents(p?.YesAsk)}, NO {Cents(p?.NoAsk)}. Closes {p?.CloseDisplay}.",
        }, "yes-no"));

        // 2. Why matched
        var why = new List<string>
        {
            $"Event names match {d.EventSimilarity:0}% (the match score for the whole pair is {c.Score:0}/100).",
        };
        if (d.Numbers.Count > 0) why.Add($"Both use the same line: {string.Join(", ", d.Numbers.Select(TrimNumber))}.");
        if (d.Qualifiers.Count > 0) why.Add($"Both are about the same part or type of event: {string.Join(", ", d.Qualifiers)}.");
        why.Add(d.PropKind.FirstOrDefault() switch
        {
            "spread" => "Both are spread bets (win by more than a margin).",
            "total" => d.PropKind.ElementAtOrDefault(1) == "team" ? "Both are team-total bets (one team's score over/under)." : "Both are game-total bets (combined score over/under).",
            _ => "Both are plain outcome bets (who/what wins).",
        });
        if (!string.IsNullOrEmpty(d.KalshiEntity) || !string.IsNullOrEmpty(d.PmusEntity))
            why.Add($"Outcome named: Kalshi {Q(Or(d.KalshiEntity, "(in the event title)"))}, Polymarket {Q(Or(d.PmusEntity, "(in the event title)"))}.");
        if (d.DateGapDays is double gap)
            why.Add(gap <= 1 ? $"Dates line up (within {Duration(gap)})." : $"Dates are {gap:0.#} days apart, so make sure it's the same event and not the next one.");
        why.Add("A high score means the wording lines up. It does not prove the rules are identical.");
        sections.Add(new("Why these were matched", why, "match-score"));

        // 3. Same or inverse
        sections.Add(new("Same or Inverse?", OrientationLines(c, d), "same-inverse"));

        // 4. Price gap
        var combo = BestCombo(c);
        var gapLines = new List<string>();
        var level = VerdictLevel.None;
        string summary;
        if (combo is null)
        {
            gapLines.Add("One side has no live price right now, so there's nothing to compare yet. Approving lets the scanner watch it.");
            summary = "No live prices to compare yet.";
        }
        else
        {
            var (ks, ps, cost, fees) = combo.Value;
            var net = 1 - cost - fees;
            gapLines.Add($"Cheapest hedge now: Kalshi {Side(ks)} + Polymarket {Side(ps)} = {C(cost)} before fees, about {C(fees)} in fees → {(net >= 0 ? "about " + C(net) + " profit" : "a loss of about " + C(-net))} per pair.");
            if (cost < 0.9)
            {
                gapLines.Add($"A gap this large ({C(1 - cost)}) almost never happens for truly identical markets. It usually means the two questions differ (team, line, period or rules). Be extra careful.");
                level = VerdictLevel.Caution;
                summary = $"Suspiciously big gap ({C(1 - cost)}). Likely not the same bet; read carefully.";
            }
            else if (net > 0)
            {
                gapLines.Add("There's a visible arb at the top of the books right now. If the pair really matches, approving lets the scanner size it and alert you.");
                level = VerdictLevel.Good;
                summary = $"Visible gap of about {C(net)} after fees, if the markets truly match.";
            }
            else
            {
                gapLines.Add("No arb right now, which is normal. Prices move all day; approving lets the scanner catch the moment one appears.");
                summary = c.Inverted ? "Looks like an inverse match. No gap right now." : "Looks like a direct match. No gap right now.";
            }
        }
        sections.Add(new("Is there money on the table?", gapLines, "gap"));

        // 5. Checklist
        var check = new List<string>
        {
            "Same event and date (not next week's game or a different season).",
            "Same outcome and the same line or number.",
            "Overtime / extra time: counted on both, or 'regulation time' on both?",
            "What happens if it's cancelled or postponed (void/refund vs settles anyway)?",
            "Same data source and deadline (time zone included).",
        };
        if (d.Qualifiers.Contains("draw")) check.Insert(2, "Draw/tie markets: confirm both mean a tie at the same point (end of regulation vs after extra time).");
        if (d.DateGapDays is > 1) check.Insert(0, $"The dates differ by {d.DateGapDays:0.#} days. Confirm it's really the same event.");
        check.Add("Tap Rules to read both exchanges' fine print side by side.");
        sections.Add(new("Before you approve, check", check, "rules"));

        // 6. What happens
        sections.Add(new("What your choice does", new[]
        {
            $"Same / Inverse: the scanner starts checking both order books every ~30 s. If buying both sides costs less than $1 after fees, by at least {s.MinEdgeCents:0.#}¢ per contract and {D(s.MinProfitDollars)} total, you get a push and a paper trade opens.",
            "Reject: hides this suggestion permanently.",
            "Unsure? Reject. A missed arb costs nothing; a wrong pair can lose both sides.",
        }));

        return new Explanation("Explain this pair", summary, level, sections);
    }

    static IReadOnlyList<string> OrientationLines(Candidate c, MatchDetails d) => d.Orientation switch
    {
        "inverse_head_to_head" => new[]
        {
            $"Polymarket runs this game as one market: YES = {Q(c.Pmus?.Title)}, NO = {Q(Or(d.PmusNoSide, "the other side"))}.",
            $"Kalshi's market is about {Q(c.Kalshi?.Title)}, which is Polymarket's NO side.",
            "So Kalshi YES = Polymarket NO → choose Inverse. Choosing Same would make you bet on the same team twice.",
        },
        "inverse_flipped_spread" => new[]
        {
            $"Polymarket's title says {Q(c.Pmus?.Title)}, but its YES side is actually the other team getting the points (the '+' line).",
            "So Polymarket YES means the title does NOT happen. Check: Polymarket's YES price should look like Kalshi's NO price.",
            $"Kalshi YES = Polymarket NO → choose Inverse.",
        },
        _ => new[]
        {
            $"Kalshi YES ({Q(c.Kalshi?.Title)}) and Polymarket YES ({Q(c.Pmus?.Title)}) describe the same outcome → choose Same.",
            "Sanity check: Kalshi's YES price and Polymarket's YES price should be close (within a few cents).",
        },
    };

    static string PmusYesMeaning(MarketView? p, MatchDetails d)
    {
        if (p is null) return "";
        if (d.HeadToHead) return $"YES pays if {Q(p.Title)} wins; NO pays if {Q(Or(d.PmusNoSide, "the other side"))} wins.";
        if (d.Flipped) return "Careful: on this market YES is the opposite of the title (the underdog covering).";
        return "YES pays $1 if that happens.";
    }

    // ======================================================================================== opportunities

    public static Explanation ExplainOpportunity(Opportunity o, ScannerSettings s)
    {
        var sections = new List<ExplanationSection>();
        var n = o.Contracts;
        var spent = o.Cost + o.Fees;
        var k = o.Pair?.Kalshi;
        var p = o.Pair?.Pmus;

        sections.Add(new("The trade, step by step", new[]
        {
            $"1. Buy {n:N0} {Side(o.KSide)} on Kalshi ({Q(k?.Title ?? o.Pair?.KalshiId)}) at {C(o.KAvg)} average = {D(o.KCost)} + {D(o.KFee)} fee.",
            $"2. Buy {n:N0} {Side(o.PSide)} on Polymarket US ({Q(p?.Title ?? o.Pair?.PmusId)}) at {C(o.PAvg)} average = {D(o.PCost)} + {D(o.PFee)} fee.",
            $"3. Total spent: {D(spent)}.",
            $"4. When it settles, exactly one side pays $1 × {n:N0} = {D(n)}.",
            $"5. Locked-in profit: {D(n)} − {D(spent)} = {D(o.Profit)} ({o.EdgeCents:0.##}¢ per contract, {o.Roi * 100:0.##}% return).",
        }, "arbitrage"));

        sections.Add(new("Why one side must pay", WhyHedged(o), "same-inverse"));

        // Verdict
        var reasons = new List<string>();
        var level = VerdictLevel.Good;
        void Flag(VerdictLevel l, string why)
        {
            reasons.Add(why);
            if (l > level) level = l;
        }
        if (o.EdgeCents < 1 || o.Profit < 1)
            Flag(VerdictLevel.Bad, $"Edge {o.EdgeCents:0.##}¢ / profit {D(o.Profit)} is too thin to survive a normal price move.");
        else if (o.EdgeCents < 2)
            Flag(VerdictLevel.Caution, $"Edge is {o.EdgeCents:0.##}¢ per contract. A 1–2¢ move on either exchange before you finish erases it.");
        else
            reasons.Add($"Edge of {o.EdgeCents:0.##}¢ per contract leaves room for small price moves.");

        if (o.DaysToClose is double days)
        {
            var ann = o.Annualized is double a ? $"{a * 100:0}% per year" : "an unknown yearly rate";
            if (days > 30 && (o.Annualized ?? 0) < 0.10)
                Flag(VerdictLevel.Caution, $"Your {D(spent)} is tied up for {Duration(days)} for {o.Roi * 100:0.##}%, which is only {ann}. Cash elsewhere might do better.");
            else
                reasons.Add($"Money is tied up for {Duration(days)}, which works out to {ann}.");
        }

        if (o.Pair?.Inverted == true)
            Flag(VerdictLevel.Caution, "This is an Inverse pair. Double-check that Kalshi YES really is Polymarket NO before trusting it.");
        if (o.Pair?.MatchDetails?.Flipped == true)
            Flag(VerdictLevel.Caution, "Polymarket's market here is a 'flipped' spread (YES = the opposite of its title).");

        var verdict = level switch
        {
            VerdictLevel.Good => $"Solid: {o.EdgeCents:0.#}¢ per contract, {D(o.Profit)} total.",
            VerdictLevel.Caution => "Real but marginal. Read the risks below.",
            _ => "Not worth acting on.",
        };
        sections.Add(new("Is it worth it?", reasons, "edge"));

        // Risks
        var risks = new List<string>
        {
            "Resolution risk: if the exchanges settle this differently, both sides can lose. This is the big one; read both rules.",
            $"Leg risk: you place two separate orders. A {o.EdgeCents:0.#}¢ move against you on either side before the second fills wipes out the profit.",
        };
        if (o.KTopSize is double kt && kt < n)
            risks.Add($"Thin Kalshi book: only {kt:N0} contracts at the best price; the rest fill at worse prices (already in the average).");
        if (o.PTopSize is double pt && pt < n)
            risks.Add($"Thin Polymarket book: only {pt:N0} contracts at the best price; the rest fill at worse prices (already in the average).");
        if (o.DaysToClose is < 0.25)
            risks.Add("Closes within hours, so it may be a live game. Prices can move in seconds.");
        if (o.DaysToClose is > 90)
            risks.Add("Long-dated: a lot can change (rule clarifications, delistings) before it settles.");
        sections.Add(new("Risks for this one", risks, "leg-risk"));

        // Real-world steps
        var thinner = (o.KTopSize ?? double.MaxValue) <= (o.PTopSize ?? double.MaxValue) ? "Kalshi" : "Polymarket US";
        sections.Add(new("If you did this for real", new[]
        {
            "This app only paper-trades. These are the steps a careful trader would take:",
            $"Place the thinner side first ({thinner}), so if it doesn't fill you haven't bought the other side.",
            $"Use limit orders at the shown prices (Kalshi {C(o.KAvg)}, Polymarket {C(o.PAvg)}), never market orders.",
            $"Don't exceed {n:N0} contracts; above that, prices get worse.",
            "Read both exchanges' resolution rules first (buttons below).",
        }, "paper"));

        return new Explanation("Explain this opportunity", verdict, level, sections);
    }

    static IReadOnlyList<string> WhyHedged(Opportunity o)
    {
        var k = o.Pair?.Kalshi?.Title ?? "the Kalshi market";
        var p = o.Pair?.Pmus?.Title ?? "the Polymarket market";
        if (o.Pair?.Inverted == true)
            return new[]
            {
                $"This pair is Inverse: Kalshi's {Q(k)} YES is the same outcome as Polymarket's NO.",
                $"You hold Kalshi {Side(o.KSide)} and Polymarket {Side(o.PSide)}: one covers the outcome happening, the other covers it not happening.",
            };
        return new[]
        {
            $"Both markets ask the same question ({Q(k)}).",
            $"You hold {Side(o.KSide)} on Kalshi and {Side(o.PSide)} on Polymarket: opposite answers, so exactly one pays $1.",
        };
    }

    // ============================================================================================ positions

    public static Explanation ExplainPosition(PaperPosition pos)
    {
        var n = pos.Contracts;
        var sections = new List<ExplanationSection>
        {
            new("What you (pretend) bought", new[]
            {
                $"{n:N0} {Side(pos.KSide)} on Kalshi at {C(pos.KAvg)} = {D(pos.KCost)} + {D(pos.KFee)} fee.",
                $"{n:N0} {Side(pos.PSide)} on Polymarket US at {C(pos.PAvg)} = {D(pos.PCost)} + {D(pos.PFee)} fee.",
                $"Total spent: {D(pos.Spent)}.",
            }, "paper"),
        };

        if (pos.Status != "settled")
        {
            sections.Add(new("What happens next", new[]
            {
                $"When both markets settle, one side should pay {D(n)}, for a profit of {D(n - pos.Spent)}.",
                "The scanner checks settlements hourly. If the exchanges disagree, this becomes a divergent resolution.",
            }, "settlement"));
            return new Explanation("Explain this position", $"Open: expecting +{D(n - pos.Spent)} at settlement.", VerdictLevel.None, sections);
        }

        string Result(double? v) => v switch { 1.0 => "YES", 0.0 => "NO", null => "unknown", _ => $"split ({v:0.##})" };
        var lines = new List<string>
        {
            $"Kalshi settled {Result(pos.KResult)}; Polymarket US settled {Result(pos.PResult)}.",
            $"Payout {D(pos.Payout ?? 0)} − spent {D(pos.Spent)} = {(pos.Pnl >= 0 ? "+" : "")}{D(pos.Pnl ?? 0)}.",
        };
        if (pos.Divergent)
        {
            lines.Add("DIVERGENT: the two exchanges didn't settle these as opposite outcomes, so the hedge failed.");
            lines.Add("Likely causes: different rules (overtime, deadline, data source), a wrong Same/Inverse choice, or markets that only looked alike.");
            lines.Add("What to do: remove this pair, and be stricter approving similar markets (same sport, prop type or wording).");
            return new Explanation("Explain this position", $"Divergent: {D(pos.Pnl ?? 0)}. The pair wasn't really the same bet.", VerdictLevel.Bad, new[]
            {
                sections[0], new ExplanationSection("What happened", lines, "divergent"),
            });
        }
        lines.Add("The hedge worked: exactly one side paid out, as expected.");
        sections.Add(new("What happened", lines, "settlement"));
        return new Explanation("Explain this position", $"Settled as expected: {(pos.Pnl >= 0 ? "+" : "")}{D(pos.Pnl ?? 0)}.", VerdictLevel.Good, sections);
    }

    // ============================================================================================ helpers

    static string Cents(double? v) => v is null ? "–" : $"{v * 100:0.#}¢";
    static string Or(string? s, string fallback) => string.IsNullOrWhiteSpace(s) ? fallback : s;
    static string TrimNumber(string n) => double.TryParse(n, System.Globalization.NumberStyles.Float,
        System.Globalization.CultureInfo.InvariantCulture, out var v) ? v.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture) : n;
}
