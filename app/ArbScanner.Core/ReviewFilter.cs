using System.Globalization;

namespace ArbScanner.Models;

/// <summary>Review screen filters. Maps 1:1 to /api/candidates query parameters; persisted on the phone.</summary>
public class ReviewFilter
{
    public int MinRating { get; set; } = 1;
    /// <summary>any | outcome | spread | total</summary>
    public string Kind { get; set; } = "any";
    /// <summary>any | same | inverse</summary>
    public string Orientation { get; set; } = "any";
    public bool HasGap { get; set; }
    /// <summary>null = any time</summary>
    public double? ClosesWithinDays { get; set; }
    /// <summary>rating | gap | closing | score</summary>
    public string Sort { get; set; } = "rating";
    public string Query { get; set; } = "";

    public static readonly IReadOnlyList<(string Value, string Label)> Kinds =
        new[] { ("any", "All bet types"), ("outcome", "Who wins"), ("spread", "Spreads (win by X)"), ("total", "Totals (over/under)") };

    public static readonly IReadOnlyList<(string Value, string Label)> Orientations =
        new[] { ("any", "Same and Inverse"), ("same", "Same only"), ("inverse", "Inverse only") };

    public static readonly IReadOnlyList<(double? Value, string Label)> Closing =
        new (double?, string)[] { (null, "Any time"), (1, "Within 24 hours"), (7, "Within 7 days"), (30, "Within 30 days") };

    public static readonly IReadOnlyList<(string Value, string Label)> Sorts =
        new[]
        {
            ("rating", "Best rating first"), ("annualized", "Highest yearly return"), ("roi", "Highest return %"),
            ("gap", "Biggest gap (¢ per contract)"), ("closing", "Closing soonest"), ("score", "Best name match"),
        };

    public bool SortsByReturn => Sort is "roi" or "annualized";

    public ReviewFilter Clone() => (ReviewFilter)MemberwiseClone();

    /// <summary>Filter-only parameters (shared by the list and the count endpoints).</summary>
    public string ToQuery()
    {
        var parts = new List<string>();
        if (MinRating > 1) parts.Add($"min_rating={MinRating}");
        if (Kind != "any") parts.Add($"kind={Kind}");
        if (Orientation != "any") parts.Add($"orientation={Orientation}");
        if (HasGap) parts.Add("has_gap=true");
        if (ClosesWithinDays is double d) parts.Add($"closes_within_days={d.ToString(CultureInfo.InvariantCulture)}");
        if (!string.IsNullOrWhiteSpace(Query)) parts.Add($"q={Uri.EscapeDataString(Query.Trim())}");
        return string.Join("&", parts);
    }

    /// <summary>Number of filters narrowing the list (search and sort excluded).</summary>
    public int ActiveCount =>
        (MinRating > 1 ? 1 : 0) + (Kind != "any" ? 1 : 0) + (Orientation != "any" ? 1 : 0) + (HasGap ? 1 : 0) +
        (ClosesWithinDays is null ? 0 : 1);

    public string Describe()
    {
        var bits = new List<string>();
        if (MinRating > 1) bits.Add($"rating {MinRating}+");
        if (Kind != "any") bits.Add(Kinds.First(k => k.Value == Kind).Label.ToLowerInvariant());
        if (Orientation != "any") bits.Add(Orientation == "same" ? "Same only" : "Inverse only");
        if (HasGap) bits.Add("gap now");
        if (ClosesWithinDays is double d) bits.Add(d <= 1 ? "closing ≤24h" : $"closing ≤{d:0}d");
        return bits.Count == 0 ? "No filters" : string.Join(" · ", bits);
    }
}
