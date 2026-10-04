namespace ArbScanner.Learning;

public enum VerdictLevel { None, Good, Caution, Bad }

/// <summary>A heading plus plain-English lines. <see cref="Term"/> optionally links the heading to a glossary entry.</summary>
public record ExplanationSection(string Heading, IReadOnlyList<string> Lines, string? Term = null);

/// <summary>A teaching walkthrough for one pair, opportunity or position, built from its real numbers.</summary>
public record Explanation(string Title, string Summary, VerdictLevel Level, IReadOnlyList<ExplanationSection> Sections)
{
    public string LevelLabel => Level switch
    {
        VerdictLevel.Good => "Looks good",
        VerdictLevel.Caution => "Be careful",
        VerdictLevel.Bad => "Not worth it",
        _ => "",
    };
}
