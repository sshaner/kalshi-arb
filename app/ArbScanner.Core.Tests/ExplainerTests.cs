using ArbScanner.Learning;
using ArbScanner.Models;
using Xunit;

namespace ArbScanner.Core.Tests;

public class ExplainerTests
{
    static readonly ScannerSettings Settings = new() { MinEdgeCents = 1, MinProfitDollars = 1 };

    static Opportunity Opp(double edgeCents = 6.58, double? days = 5, bool inverted = false) => new()
    {
        KSide = "yes", KAvg = 0.40, KCost = 40.00, KFee = 1.68,
        PSide = "no", PAvg = 0.50, PCost = 50.00, PFee = 1.74,
        Contracts = 100, Cost = 90.00, Fees = 3.42, Profit = 6.58, EdgeCents = edgeCents, Roi = 6.58 / 93.42,
        Annualized = 6.58 / 93.42 * 365 / 5, DaysToClose = days, KTopSize = 100, PTopSize = 40,
        Pair = new Pair
        {
            Inverted = inverted,
            Kalshi = new MarketView { Title = "Over 45.5 points", EventTitle = "KC vs LV" },
            Pmus = new MarketView { Title = "Over 45.5 total points", EventTitle = "KC vs. LV" },
        },
    };

    static string All(Explanation e) => string.Join("\n", e.Sections.SelectMany(s => s.Lines)) + "\n" + e.Summary;

    [Fact]
    public void Opportunity_walkthrough_uses_the_real_numbers()
    {
        var text = All(Explainer.ExplainOpportunity(Opp(), Settings));
        Assert.Contains("Buy 100 YES on Kalshi", text);
        Assert.Contains("at 40¢ average = $40.00 + $1.68 fee", text);
        Assert.Contains("Buy 100 NO on Polymarket US", text);
        Assert.Contains("Total spent: $93.42", text);
        Assert.Contains("$1 × 100 = $100.00", text);
        Assert.Contains("$6.58 (6.58¢ per contract", text);
    }

    [Fact]
    public void Thin_book_and_thinner_side_first_are_explained()
    {
        var text = All(Explainer.ExplainOpportunity(Opp(), Settings));
        Assert.Contains("only 40 contracts at the best price", text);
        Assert.Contains("thinner side first (Polymarket US)", text);
    }

    [Theory]
    [InlineData(6.58, 5, VerdictLevel.Good)]
    [InlineData(1.5, 5, VerdictLevel.Caution)]
    [InlineData(0.5, 5, VerdictLevel.Bad)]
    public void Verdict_follows_edge(double edge, double days, VerdictLevel expected)
    {
        var o = Opp(edge, days);
        if (edge < 1) o.Profit = 0.5;
        Assert.Equal(expected, Explainer.ExplainOpportunity(o, Settings).Level);
    }

    [Fact]
    public void Slow_low_return_is_flagged()
    {
        var o = Opp(days: 200);
        o.Annualized = 0.05;
        var e = Explainer.ExplainOpportunity(o, Settings);
        Assert.Equal(VerdictLevel.Caution, e.Level);
        Assert.Contains("tied up for about 200 days", All(e));
    }

    [Fact]
    public void Inverse_pair_says_so()
    {
        var text = All(Explainer.ExplainOpportunity(Opp(inverted: true), Settings));
        Assert.Contains("This pair is Inverse", text);
    }

    static Candidate Cand(double? kYes, double? kNo, double? pYes, double? pNo, string orientation = "same", bool inverted = false) => new()
    {
        Score = 98, Inverted = inverted,
        Kalshi = new MarketView { EventTitle = "USC vs Penn State", Title = "Penn State", YesAsk = kYes, NoAsk = kNo },
        Pmus = new MarketView { EventTitle = "USC vs. Penn State", Title = "USC", AltTitle = "Penn State", YesAsk = pYes, NoAsk = pNo },
        MatchDetails = new MatchDetails { Orientation = orientation, HeadToHead = true, PmusNoSide = "Penn State", EventSimilarity = 100 },
    };

    [Fact]
    public void Head_to_head_inverse_is_explained_with_names()
    {
        var e = Explainer.ExplainCandidate(Cand(0.40, 0.62, 0.61, 0.41, "inverse_head_to_head", true), Settings);
        var text = All(e);
        Assert.Contains("YES = “USC”, NO = “Penn State”", text);
        Assert.Contains("choose Inverse", text);
    }

    [Fact]
    public void Best_combo_respects_orientation()
    {
        var combo = Explainer.BestCombo(Cand(0.40, 0.62, 0.61, 0.41, inverted: true));
        Assert.NotNull(combo);
        // Inverse: Kalshi YES + Polymarket YES (40 + 61 = 101¢) beats Kalshi NO + Polymarket NO (62 + 41 = 103¢).
        Assert.Equal(("yes", "yes"), (combo!.Value.kSide, combo.Value.pSide));
        Assert.Equal(1.01, combo.Value.cost, 6);
    }

    [Fact]
    public void Huge_gap_is_treated_as_suspicious()
    {
        var e = Explainer.ExplainCandidate(Cand(0.20, 0.81, 0.85, 0.17), Settings);
        Assert.Equal(VerdictLevel.Caution, e.Level);
        Assert.Contains("almost never happens", All(e));
    }

    [Fact]
    public void Divergent_position_is_bad_and_tells_you_what_to_do()
    {
        var pos = new PaperPosition
        {
            Contracts = 10, KSide = "yes", KAvg = .4, KCost = 4, KFee = .17, PSide = "no", PAvg = .5, PCost = 5, PFee = .18,
            Status = "settled", KResult = 0, PResult = 1, Payout = 0, Pnl = -9.35, Divergent = true,
        };
        var e = Explainer.ExplainPosition(pos);
        Assert.Equal(VerdictLevel.Bad, e.Level);
        Assert.Contains("remove this pair", All(e));
    }
}

public class GlossaryTests
{
    [Fact]
    public void Every_referenced_term_exists()
    {
        var referenced = HelpText.Settings.Values.Select(s => s.Term)
            .Concat(new[] { "arbitrage", "yes-no", "match-score", "same-inverse", "gap", "rules", "edge", "leg-risk",
                            "paper", "settlement", "divergent", "roi", "annualized", "contract", "profit", "fees",
                            "order-book", "head-to-head", "flipped-spread", "lockup", "ask-bid" });
        foreach (var id in referenced.Distinct())
            Assert.True(Glossary.Find(id) is not null, $"missing glossary entry '{id}'");
    }

    [Fact]
    public void Ids_are_unique_and_entries_complete()
    {
        Assert.Equal(Glossary.Entries.Count, Glossary.Entries.Select(e => e.Id).Distinct().Count());
        Assert.All(Glossary.Entries, e =>
        {
            Assert.False(string.IsNullOrWhiteSpace(e.Meaning));
            Assert.False(string.IsNullOrWhiteSpace(e.HowItAffectsYou));
            Assert.False(string.IsNullOrWhiteSpace(e.Example));
        });
    }

    [Fact]
    public void Search_finds_by_term()
    {
        Assert.Contains(Glossary.Search("annual"), e => e.Id == "annualized");
    }
}

public class RatingAndFilterTests
{
    [Fact]
    public void Rating_section_lists_reasons_and_meaning()
    {
        var s = Explainer.RatingSection(9, "Excellent", new[] { "Match score 100/100", "6.4¢ per contract after fees (+)" });
        Assert.NotNull(s);
        Assert.Equal("Deal rating: 9/10", s!.Heading);
        Assert.Contains(s.Lines, l => l.Contains("Factor: 6.4¢"));
        Assert.Contains(s.Lines, l => l.Contains("isn't risk-free"));
        Assert.NotNull(Glossary.Find("deal-rating"));
    }

    [Fact]
    public void Filter_builds_query_and_description()
    {
        var f = new ReviewFilter { MinRating = 8, Kind = "spread", HasGap = true, ClosesWithinDays = 1, Query = "Chiefs vs" };
        Assert.Equal("min_rating=8&kind=spread&has_gap=true&closes_within_days=1&q=Chiefs%20vs", f.ToQuery());
        Assert.Equal(4, f.ActiveCount);
        Assert.Equal("rating 8+ · spreads (win by x) · gap now · closing ≤24h", f.Describe());
        Assert.Equal("", new ReviewFilter().ToQuery());
    }
}
