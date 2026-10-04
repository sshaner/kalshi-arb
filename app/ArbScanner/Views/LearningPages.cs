using ArbScanner.Controls;
using ArbScanner.Learning;
using ArbScanner.Services;

namespace ArbScanner.Views;

/// <summary>Modal page with a Close button; the base for every teaching page.</summary>
public abstract class LearningModalPage : ContentPage
{
    protected View Wrap(string title, View body)
    {
        var close = new Button { Text = "Close", HorizontalOptions = LayoutOptions.End };
        close.Clicked += async (_, _) => await Navigation.PopModalAsync();
        var header = new Grid { ColumnDefinitions = { new(GridLength.Star), new(GridLength.Auto) }, Padding = new Thickness(16, 56, 16, 8) };
        header.Add(Theme.Text(title, "H1"));
        header.Add(close, 1);
        var grid = new Grid { RowDefinitions = { new(GridLength.Auto), new(GridLength.Star) } };
        grid.Add(header);
        grid.Add(body, 0, 1);
        return grid;
    }
}

/// <summary>One glossary term: what it means, how it should affect your choices, an example.</summary>
public class GlossaryEntryPage : LearningModalPage
{
    public GlossaryEntryPage(GlossaryEntry e)
    {
        Content = Wrap(e.Term, new ScrollView
        {
            Content = new VerticalStackLayout
            {
                Padding = new Thickness(16, 0, 16, 32),
                Spacing = 14,
                Children =
                {
                    Section("What it means", e.Meaning),
                    Section("How it should affect your choices", e.HowItAffectsYou),
                    Section("Example", e.Example),
                },
            },
        });
    }

    static View Section(string heading, string body) => new Border
    {
        Style = Theme.Style("Card"),
        Content = new VerticalStackLayout { Spacing = 6, Children = { Theme.Text(heading, "H2", Theme.Get("Accent")), Theme.Text(body) } },
    };
}

/// <summary>Searchable list of every term.</summary>
public class GlossaryPage : LearningModalPage
{
    public GlossaryPage()
    {
        var list = new CollectionView
        {
            SelectionMode = SelectionMode.Single,
            ItemsSource = Glossary.Entries,
            ItemTemplate = new DataTemplate(() =>
            {
                var term = Theme.Text("", "H2");
                term.SetBinding(Label.TextProperty, static (GlossaryEntry e) => e.Term);
                var meaning = Theme.Text("", "Muted");
                meaning.MaxLines = 2;
                meaning.LineBreakMode = LineBreakMode.TailTruncation;
                meaning.SetBinding(Label.TextProperty, static (GlossaryEntry e) => e.Meaning);
                return new Border
                {
                    Style = Theme.Style("Card"),
                    Margin = new Thickness(0, 0, 0, 8),
                    Content = new VerticalStackLayout { Spacing = 2, Children = { term, meaning } },
                };
            }),
        };
        list.SelectionChanged += async (_, args) =>
        {
            if (args.CurrentSelection.FirstOrDefault() is GlossaryEntry e)
            {
                list.SelectedItem = null;
                await Navigation.PushModalAsync(new GlossaryEntryPage(e));
            }
        };
        var search = new SearchBar { Placeholder = "Search terms", TextColor = Theme.Get("Text"), PlaceholderColor = Theme.Get("MutedColor") };
        search.TextChanged += (_, a) => list.ItemsSource = Glossary.Search(a.NewTextValue).ToList();
        var body = new Grid { RowDefinitions = { new(GridLength.Auto), new(GridLength.Star) }, Padding = new Thickness(16, 0) };
        body.Add(search);
        body.Add(list, 0, 1);
        Content = Wrap("Glossary", body);
    }
}

/// <summary>Full explanation for a pair/opportunity/position, opened on demand (ignores the Learning switch).</summary>
public class ExplanationPage : LearningModalPage
{
    public ExplanationPage(Explanation e, string? extraHeading = null, string? extraText = null)
    {
        var stack = new VerticalStackLayout
        {
            Padding = new Thickness(16, 0, 16, 32),
            Spacing = 12,
            Children = { new ExplanationView { Explanation = e, AlwaysShow = true } },
        };
        if (extraHeading is not null && !string.IsNullOrWhiteSpace(extraText))
        {
            stack.Add(new Border
            {
                Style = Theme.Style("Card"),
                Content = new VerticalStackLayout { Spacing = 6, Children = { Theme.Text(extraHeading, "H2"), Theme.Text(extraText, "Muted") } },
            });
        }
        Content = Wrap(e.Title, new ScrollView { Content = stack });
    }
}

/// <summary>Swipeable first-run tutorial; replayable from Settings.</summary>
public class TutorialPage : ContentPage
{
    public TutorialPage()
    {
        var cards = HelpText.Tutorial;
        var carousel = new CarouselView
        {
            ItemsSource = cards,
            Loop = false,
            ItemTemplate = new DataTemplate(() =>
            {
                var glyph = Theme.Text("", color: Theme.Get("Accent"));
                glyph.FontSize = 54;
                glyph.HorizontalTextAlignment = TextAlignment.Center;
                glyph.SetBinding(Label.TextProperty, static (TutorialCard c) => c.Glyph);
                var title = Theme.Text("", "H1");
                title.HorizontalTextAlignment = TextAlignment.Center;
                title.SetBinding(Label.TextProperty, static (TutorialCard c) => c.Title);
                var body = Theme.Text("");
                body.FontSize = 16;
                body.SetBinding(Label.TextProperty, static (TutorialCard c) => c.Body);
                return new ScrollView
                {
                    Content = new VerticalStackLayout
                    {
                        Padding = new Thickness(28, 24),
                        Spacing = 18,
                        Children = { glyph, title, body },
                    },
                };
            }),
        };
        var indicators = new IndicatorView
        {
            IndicatorColor = Theme.Get("Border"),
            SelectedIndicatorColor = Theme.Get("Accent"),
            HorizontalOptions = LayoutOptions.Center,
            Margin = new Thickness(0, 8),
        };
        carousel.IndicatorView = indicators;

        var skip = new Button { Text = "Skip", BackgroundColor = Colors.Transparent, TextColor = Theme.Get("MutedColor") };
        var next = new Button { Text = "Next", Style = Theme.Style("Primary") };
        async Task Finish()
        {
            LearningMode.Current.TutorialSeen = true;
            await Navigation.PopModalAsync();
        }
        skip.Clicked += async (_, _) => await Finish();
        next.Clicked += async (_, _) =>
        {
            if (carousel.Position >= cards.Count - 1) await Finish();
            else carousel.Position += 1;
        };
        carousel.PositionChanged += (_, a) => next.Text = a.CurrentPosition >= cards.Count - 1 ? "Start using the app" : "Next";

        var buttons = new Grid { ColumnDefinitions = { new(GridLength.Auto), new(GridLength.Star) }, Padding = new Thickness(20, 0, 20, 36), ColumnSpacing = 12 };
        buttons.Add(skip);
        buttons.Add(next, 1);

        var grid = new Grid { RowDefinitions = { new(GridLength.Star), new(GridLength.Auto), new(GridLength.Auto) }, Padding = new Thickness(0, 48, 0, 0) };
        grid.Add(carousel);
        grid.Add(indicators, 0, 1);
        grid.Add(buttons, 0, 2);
        Content = grid;
    }

    protected override bool OnBackButtonPressed() => true;
}
