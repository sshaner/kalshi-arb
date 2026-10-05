using System.Text.Json.Serialization;
using ArbScanner.Learning;

namespace ArbScanner.Models;

// Shapes mirror server/arb/api.py. JSON is snake_case; ApiClient maps it via JsonNamingPolicy.SnakeCaseLower.

public class MarketView
{
    public string Venue { get; set; } = "";
    public string MarketId { get; set; } = "";
    public string EventTitle { get; set; } = "";
    public string Title { get; set; } = "";
    public string? CloseTime { get; set; }
    public string? EventTime { get; set; }
    public string? Url { get; set; }
    public string? Rules { get; set; }
    public double? YesAsk { get; set; }
    public double? NoAsk { get; set; }
    public string? AltTitle { get; set; }
    public bool Flipped { get; set; }

    public string Display => string.IsNullOrWhiteSpace(EventTitle) ? Title : $"{EventTitle} — {Title}";
    public string Quote => $"Y {Cents(YesAsk)}  ·  N {Cents(NoAsk)}";
    public string CloseDisplay => Fmt.Date(CloseTime);

    static string Cents(double? v) => v is null ? "–" : $"{v * 100:0.#}¢";
}

/// <summary>Why the server paired two markets (server/arb/matcher.py match_details).</summary>
public class MatchDetails
{
    public List<string> Numbers { get; set; } = new();
    public List<string> Qualifiers { get; set; } = new();
    public List<string> PropKind { get; set; } = new();
    public string KalshiEntity { get; set; } = "";
    public string PmusEntity { get; set; } = "";
    public string PmusNoSide { get; set; } = "";
    public bool HeadToHead { get; set; }
    public bool Flipped { get; set; }
    public double? DateGapDays { get; set; }
    /// <summary>same | inverse_head_to_head | inverse_flipped_spread | mismatch</summary>
    public string Orientation { get; set; } = "same";
    public double EventSimilarity { get; set; }
}

public class Pair
{
    public long Id { get; set; }
    public string KalshiId { get; set; } = "";
    public string PmusId { get; set; } = "";
    public bool Inverted { get; set; }
    public bool Paused { get; set; }
    public string? Notes { get; set; }
    public string Status { get; set; } = "";
    public double? LastChecked { get; set; }
    public string? LastError { get; set; }
    public MarketView? Kalshi { get; set; }
    public MarketView? Pmus { get; set; }
    public MatchDetails? MatchDetails { get; set; }

    public string Title => Kalshi?.Display ?? KalshiId;
    public string Subtitle => (Inverted ? "Inverted · " : "") + (Paused ? "Paused · " : "") + $"checked {Fmt.Ago(LastChecked)}";
}

public class Candidate
{
    public long Id { get; set; }
    public string KalshiId { get; set; } = "";
    public string PmusId { get; set; } = "";
    public double Score { get; set; }
    public double? EstCost { get; set; }
    public bool Inverted { get; set; }
    public MarketView? Kalshi { get; set; }
    public MarketView? Pmus { get; set; }
    public MatchDetails? MatchDetails { get; set; }

    // 1-10 deal rating, computed on the server every discovery pass (server/arb/rating.py)
    public int? Rating { get; set; }
    public string? RatingLabel { get; set; }
    public double? Confidence { get; set; }
    public double? NetCents { get; set; }
    public string? Kind { get; set; }
    public string? ClosesAt { get; set; }
    public List<string> RatingReasons { get; set; } = new();
    /// <summary>Profit per dollar spent at last-scan prices (after fees); null when there's no gap.</summary>
    public double? Roi { get; set; }
    public double? Annualized { get; set; }

    [JsonIgnore] public string ReturnDisplay => Roi is double r
        ? $"Return {r * 100:0.##}%" + (Annualized is double a ? $" · ~{Returns.Yearly(a)}/yr" : "")
        : "No return at last-scan prices";
    [JsonIgnore] public bool HasReturn => Roi is > 0;

    [JsonIgnore] public Explanation? Explanation { get; set; }
    [JsonIgnore] public string Suggestion => Inverted ? "Suggested: Inverse" : "Suggested: Same";

    public string ScoreDisplay => $"match {Score:0}";
    public string GapDisplay => EstCost is null ? "no quote" :
        EstCost < 1 ? $"gap {(1 - EstCost.Value) * 100:0.#}¢ before fees" : $"cost {EstCost * 100:0.#}¢";
    public bool HasGap => EstCost is < 1;
}

public class Opportunity
{
    public long Id { get; set; }
    public long PairId { get; set; }
    public string Direction { get; set; } = "";
    public string KSide { get; set; } = "";
    public double KAvg { get; set; }
    public double KCost { get; set; }
    public double KFee { get; set; }
    public string PSide { get; set; } = "";
    public double PAvg { get; set; }
    public double PCost { get; set; }
    public double PFee { get; set; }
    public double Contracts { get; set; }
    public double Cost { get; set; }
    public double Fees { get; set; }
    public double Profit { get; set; }
    public double EdgeCents { get; set; }
    public double Roi { get; set; }
    public double? Annualized { get; set; }
    public double FirstSeen { get; set; }
    public double LastSeen { get; set; }
    public bool Active { get; set; }
    public Pair? Pair { get; set; }
    public BookView? KBook { get; set; }
    public BookView? PBook { get; set; }
    public double? KTopSize { get; set; }
    public double? PTopSize { get; set; }
    public double? DaysToClose { get; set; }
    public int? Rating { get; set; }
    public string? RatingLabel { get; set; }
    public double? Confidence { get; set; }
    public List<string> RatingReasons { get; set; } = new();

    [JsonIgnore] public Explanation? Explanation { get; set; }

    public string Title => Pair?.Title ?? $"Pair {PairId}";
    public string Legs => $"Kalshi {KSide.ToUpper()} {KAvg * 100:0.#}¢ + PM US {PSide.ToUpper()} {PAvg * 100:0.#}¢";
    public string EdgeDisplay => $"{EdgeCents:0.#}¢/ct";
    public string ProfitDisplay => $"${Profit:0.00} on {Contracts:0}";
    public string AnnualizedDisplay => Annualized is double a ? $"{Returns.Yearly(a)}/yr" : "";
    public string ReturnDisplay => $"Return {Roi * 100:0.##}%" + (Annualized is double y ? $" · ~{Returns.Yearly(y)}/yr" : "");
    public string SeenDisplay => $"since {Fmt.Ago(FirstSeen)}";
    public string KalshiLeg => $"Buy {Contracts:0} {KSide.ToUpper()} @ {KAvg * 100:0.##}¢ avg · cost ${KCost:0.00} · fee ${KFee:0.00}";
    public string PmusLeg => $"Buy {Contracts:0} {PSide.ToUpper()} @ {PAvg * 100:0.##}¢ avg · cost ${PCost:0.00} · fee ${PFee:0.00}";
    public string Totals => $"Total ${Cost + Fees:0.00} → pays ${Contracts:0.00} · ROI {Roi * 100:0.##}%";
}

public class BookView
{
    public List<List<double>> YesAsks { get; set; } = new();
    public List<List<double>> NoAsks { get; set; } = new();
}

public class PaperPosition
{
    public long Id { get; set; }
    public long PairId { get; set; }
    public double Contracts { get; set; }
    public string KSide { get; set; } = "";
    public double KAvg { get; set; }
    public double KCost { get; set; }
    public double KFee { get; set; }
    public string PSide { get; set; } = "";
    public double PAvg { get; set; }
    public double PCost { get; set; }
    public double PFee { get; set; }
    public double OpenedAt { get; set; }
    public string Status { get; set; } = "";
    public double? KResult { get; set; }
    public double? PResult { get; set; }
    public double? Payout { get; set; }
    public double? Pnl { get; set; }

    [JsonIgnore] public Explanation? Explanation { get; set; }
    public bool Divergent { get; set; }
    public Pair? Pair { get; set; }

    public string Title => Pair?.Title ?? $"Pair {PairId}";
    public double Spent => KCost + KFee + PCost + PFee;
    public string Detail => Status == "open"
        ? $"{Contracts:0} ct · spent ${Spent:0.00} · expected +${Contracts - Spent:0.00}"
        : $"{Contracts:0} ct · P&L {(Pnl >= 0 ? "+" : "")}${Pnl:0.00}" + (Divergent ? " · DIVERGENT" : "");
    public string Opened => Fmt.Ago(OpenedAt);
}

public class PaperSummary
{
    public int OpenCount { get; set; }
    public double OpenCapital { get; set; }
    public double OpenExpectedPnl { get; set; }
    public int SettledCount { get; set; }
    public double RealizedPnl { get; set; }
    public int DivergentCount { get; set; }
}

public class LoopStatus
{
    public double? LastRun { get; set; }
    public double? Duration { get; set; }
    public string? Error { get; set; }
    public bool Running { get; set; }
    public int KalshiMarkets { get; set; }
    public int PmusMarkets { get; set; }
    public int NewCandidates { get; set; }
    public int Pairs { get; set; }
    public int ActiveOpportunities { get; set; }
    public int Settled { get; set; }
}

public class StatusCounts
{
    public int PendingCandidates { get; set; }
    public int ActivePairs { get; set; }
    public int LiveOpportunities { get; set; }
    public double? BestEdgeCents { get; set; }
    public int Devices { get; set; }
}

public class PushStatus
{
    public bool Enabled { get; set; }
    public string? LastError { get; set; }
}

public class ServerStatus
{
    public double ServerTime { get; set; }
    public double StartedAt { get; set; }
    public LoopStatus Discovery { get; set; } = new();
    public LoopStatus Prices { get; set; } = new();
    public LoopStatus Settlement { get; set; } = new();
    public StatusCounts Counts { get; set; } = new();
    public PaperSummary Paper { get; set; } = new();
    public PushStatus Push { get; set; } = new();
    public ScannerSettings Settings { get; set; } = new();
}

public class ScannerSettings
{
    public bool ScanEnabled { get; set; } = true;
    public double MinEdgeCents { get; set; }
    public double MinProfitDollars { get; set; }
    public double MinAnnualized { get; set; }
    public double PaperMaxStake { get; set; }
    public double AlertCooldownMin { get; set; }
    public int? QuietHoursStart { get; set; }
    public int? QuietHoursEnd { get; set; }
    public double MatchMinScore { get; set; }
    public double MatchDateWindowDays { get; set; }
}

public class PushTestResult
{
    public int Sent { get; set; }
    public bool Enabled { get; set; }
    public string? LastError { get; set; }
}

public static class Fmt
{
    public static string Ago(double? unix)
    {
        if (unix is null or 0) return "never";
        var span = DateTimeOffset.UtcNow - DateTimeOffset.FromUnixTimeMilliseconds((long)(unix.Value * 1000));
        if (span.TotalSeconds < 60) return $"{Math.Max(0, (int)span.TotalSeconds)}s ago";
        if (span.TotalMinutes < 60) return $"{(int)span.TotalMinutes}m ago";
        if (span.TotalHours < 48) return $"{(int)span.TotalHours}h ago";
        return $"{(int)span.TotalDays}d ago";
    }

    public static string Date(string? iso) =>
        DateTimeOffset.TryParse(iso, out var d) ? d.ToLocalTime().ToString("MMM d, h:mm tt") : "–";
}

public class CandidateCount
{
    public int Matching { get; set; }
    public int Total { get; set; }
    public Dictionary<string, int> ByRating { get; set; } = new();
}

public static class Returns
{
    /// <summary>Yearly return as a readable %; huge values from same-day markets are capped so they don't look like typos.</summary>
    public static string Yearly(double annualized) => annualized switch
    {
        >= 100 => ">10,000%",
        >= 10 => $"{annualized * 100:N0}%",
        _ => $"{annualized * 100:0.#}%",
    };
}
