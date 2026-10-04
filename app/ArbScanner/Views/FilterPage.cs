using ArbScanner.Controls;
using ArbScanner.Models;

namespace ArbScanner.Views;

/// <summary>Review filters: minimum rating, bet type, Same/Inverse, closing window, gap-only, sort.</summary>
public class FilterPage : LearningModalPage
{
    public FilterPage(ReviewFilter current, Action<ReviewFilter> apply)
    {
        var f = current.Clone();

        var ratingValue = Theme.Text("", "H2", Theme.Get("Accent"));
        var slider = new Slider { Minimum = 1, Maximum = 10, Value = f.MinRating, MinimumTrackColor = Theme.Get("Accent") };
        void ShowRating() => ratingValue.Text = f.MinRating <= 1 ? "Any rating" : $"{f.MinRating}+ out of 10";
        slider.ValueChanged += (_, e) =>
        {
            f.MinRating = (int)Math.Round(e.NewValue);
            ShowRating();
        };
        ShowRating();

        Picker MakePicker<T>(IReadOnlyList<(T Value, string Label)> options, T selected, Action<T> set)
        {
            var p = new Picker { TextColor = Theme.Get("Text"), BackgroundColor = Theme.Get("SurfaceAlt") };
            foreach (var o in options) p.Items.Add(o.Label);
            p.SelectedIndex = Math.Max(0, options.ToList().FindIndex(o => Equals(o.Value, selected)));
            p.SelectedIndexChanged += (_, _) => set(options[Math.Max(0, p.SelectedIndex)].Value);
            return p;
        }

        var gap = new Switch { IsToggled = f.HasGap, OnColor = Theme.Get("Accent"), HorizontalOptions = LayoutOptions.End };
        gap.Toggled += (_, e) => f.HasGap = e.Value;
        var gapRow = new Grid { ColumnDefinitions = { new(GridLength.Star), new(GridLength.Auto) } };
        gapRow.Add(Theme.Text("Only pairs with a gap after fees right now"));
        gapRow.Add(gap, 1);

        var reset = new Button { Text = "Reset" };
        var applyBtn = new Button { Text = "Show results", Style = Theme.Style("Primary") };
        reset.Clicked += async (_, _) =>
        {
            apply(new ReviewFilter { Query = current.Query });
            await Navigation.PopModalAsync();
        };
        applyBtn.Clicked += async (_, _) =>
        {
            apply(f);
            await Navigation.PopModalAsync();
        };
        var buttons = new Grid { ColumnDefinitions = { new(GridLength.Star), new(new GridLength(2, GridUnitType.Star)) }, ColumnSpacing = 10 };
        buttons.Add(reset);
        buttons.Add(applyBtn, 1);

        View Block(string title, View control, string? hint = null, string? term = null)
        {
            var head = new Grid { ColumnDefinitions = { new(GridLength.Star), new(GridLength.Auto) } };
            head.Add(Theme.Text(title, "H2"));
            if (term is not null) head.Add(new InfoButton { Term = term }, 1);
            var stack = new VerticalStackLayout { Spacing = 6, Children = { head, control } };
            if (hint is not null) stack.Add(new HintLabel { Text = hint });
            return new Border { Style = Theme.Style("Card"), Content = stack };
        }

        Content = Wrap("Filters", new ScrollView
        {
            Content = new VerticalStackLayout
            {
                Padding = new Thickness(16, 0, 16, 32),
                Spacing = 12,
                Children =
                {
                    Block("Minimum deal rating", new VerticalStackLayout { Children = { ratingValue, slider } },
                        "8+ shows only strong matches with real profit after fees. Start at 7 to see the best few.", "deal-rating"),
                    Block("Bet type", MakePicker(ReviewFilter.Kinds, f.Kind, v => f.Kind = v),
                        "Plain 'who wins' markets are usually the easiest to match correctly."),
                    Block("Same or Inverse", MakePicker(ReviewFilter.Orientations, f.Orientation, v => f.Orientation = v),
                        "Same pairs are simpler to verify. Inverse pairs need one more check.", "same-inverse"),
                    Block("Closes", MakePicker(ReviewFilter.Closing, f.ClosesWithinDays, v => f.ClosesWithinDays = v),
                        "Sooner = your money is tied up for less time and results come faster.", "lockup"),
                    Block("Money on the table", gapRow,
                        "Based on prices from the last scan (up to 30 min old). The scanner re-checks live prices before alerting.", "gap"),
                    Block("Sort by", MakePicker(ReviewFilter.Sorts, f.Sort, v => f.Sort = v)),
                    buttons,
                },
            },
        });
    }
}
