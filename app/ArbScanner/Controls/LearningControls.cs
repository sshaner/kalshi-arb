using ArbScanner.Learning;
using ArbScanner.Services;
using ArbScanner.Views;

namespace ArbScanner.Controls;

static class Theme
{
    public static Color Get(string key) =>
        Application.Current?.Resources.TryGetValue(key, out var v) == true && v is Color c ? c : Colors.Gray;

    public static Style? Style(string key) =>
        Application.Current?.Resources.TryGetValue(key, out var v) == true ? v as Style : null;

    public static Label Text(string text, string? style = null, Color? color = null)
    {
        var l = new Label { Text = text, LineBreakMode = LineBreakMode.WordWrap };
        if (style is not null) l.Style = Style(style);
        if (color is not null) l.TextColor = color;
        return l;
    }
}

/// <summary>Base for controls that show only while Learning mode is on.</summary>
public abstract class LearningOnlyView : ContentView
{
    protected LearningOnlyView()
    {
        // Subscribe only while on screen: CollectionView recycles many of these, and the switch is a singleton.
        Loaded += (_, _) =>
        {
            LearningMode.Current.PropertyChanged += OnLearningChanged;
            LearningMode.Current.IntrosChanged += Refresh;
            Refresh();
        };
        Unloaded += (_, _) =>
        {
            LearningMode.Current.PropertyChanged -= OnLearningChanged;
            LearningMode.Current.IntrosChanged -= Refresh;
        };
        IsVisible = LearningMode.Current.IsOn;
    }

    void OnLearningChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(LearningMode.IsOn)) Refresh();
    }

    protected virtual bool ShouldShow => LearningMode.Current.IsOn;

    protected void Refresh() => MainThread.BeginInvokeOnMainThread(() => IsVisible = ShouldShow);
}

/// <summary>"What this screen is for / what to do here" card at the top of a page. Dismissible per screen.</summary>
public class HelpCard : LearningOnlyView
{
    public static readonly BindableProperty ScreenKeyProperty = BindableProperty.Create(
        nameof(ScreenKey), typeof(string), typeof(HelpCard), "", propertyChanged: (b, _, _) => ((HelpCard)b).Build());

    public string ScreenKey
    {
        get => (string)GetValue(ScreenKeyProperty);
        set => SetValue(ScreenKeyProperty, value);
    }

    protected override bool ShouldShow => LearningMode.Current.IsOn && !LearningMode.Current.IsIntroDismissed(ScreenKey);

    void Build()
    {
        if (!HelpText.Screens.TryGetValue(ScreenKey, out var intro)) return;
        var close = new Button
        {
            Text = "✕", FontSize = 13, Padding = new Thickness(8, 2), BackgroundColor = Colors.Transparent,
            TextColor = Theme.Get("MutedColor"), VerticalOptions = LayoutOptions.Start,
        };
        close.Clicked += (_, _) => LearningMode.Current.DismissIntro(ScreenKey);
        var header = new Grid { ColumnDefinitions = { new(GridLength.Star), new(GridLength.Auto) } };
        header.Add(Theme.Text("💡 " + intro.Title, "H2", Theme.Get("Accent")));
        header.Add(close, 1);
        Content = new Border
        {
            Style = Theme.Style("Card"),
            Stroke = Theme.Get("Accent"),
            Margin = new Thickness(0, 0, 0, 4),
            Content = new VerticalStackLayout
            {
                Spacing = 6,
                Children =
                {
                    header,
                    Theme.Text(intro.Purpose),
                    Theme.Text("What to do: " + intro.WhatToDo, "Muted"),
                },
            },
        };
        Refresh();
    }
}

/// <summary>ⓘ next to a number or term; opens its glossary entry. Hidden when Learning mode is off.</summary>
public class InfoButton : LearningOnlyView
{
    public static readonly BindableProperty TermProperty =
        BindableProperty.Create(nameof(Term), typeof(string), typeof(InfoButton), "");

    public string Term
    {
        get => (string)GetValue(TermProperty);
        set => SetValue(TermProperty, value);
    }

    public InfoButton()
    {
        var label = new Label
        {
            Text = "ⓘ", FontSize = 17, TextColor = Theme.Get("Accent"), Padding = new Thickness(6, 0),
            VerticalOptions = LayoutOptions.Center,
        };
        var tap = new TapGestureRecognizer();
        tap.Tapped += async (_, _) =>
        {
            if (Glossary.Find(Term) is { } entry)
                await Shell.Current.Navigation.PushModalAsync(new GlossaryEntryPage(entry));
        };
        label.GestureRecognizers.Add(tap);
        Content = label;
        VerticalOptions = LayoutOptions.Center;
    }
}

/// <summary>Short learning-only hint text (e.g. under a dashboard tile or a setting).</summary>
public class HintLabel : LearningOnlyView
{
    public static readonly BindableProperty TextProperty = BindableProperty.Create(
        nameof(Text), typeof(string), typeof(HintLabel), "", propertyChanged: (b, _, n) => ((HintLabel)b)._label.Text = (string)n);

    readonly Label _label = Theme.Text("", "Muted");

    public string Text
    {
        get => (string)GetValue(TextProperty);
        set => SetValue(TextProperty, value);
    }

    public HintLabel()
    {
        _label.FontSize = 12;
        _label.TextColor = Theme.Get("Accent").WithAlpha(0.85f);
        Content = _label;
    }
}

/// <summary>Help for one setting from <see cref="HelpText.Settings"/>, with an ⓘ to its glossary term.</summary>
public class SettingHelpView : LearningOnlyView
{
    public static readonly BindableProperty KeyProperty = BindableProperty.Create(
        nameof(Key), typeof(string), typeof(SettingHelpView), "", propertyChanged: (b, _, _) => ((SettingHelpView)b).Build());

    public string Key
    {
        get => (string)GetValue(KeyProperty);
        set => SetValue(KeyProperty, value);
    }

    void Build()
    {
        if (!HelpText.Settings.TryGetValue(Key, out var h)) return;
        var grid = new Grid { ColumnDefinitions = { new(GridLength.Star), new(GridLength.Auto) } };
        var text = Theme.Text($"{h.WhatItDoes} {h.RaiseLower} Suggested: {h.Suggested}.", "Muted");
        text.FontSize = 12;
        grid.Add(text);
        grid.Add(new InfoButton { Term = h.Term }, 1);
        Content = grid;
        Refresh();
    }
}

/// <summary>Renders an <see cref="Explanation"/>: verdict badge, summary, and sections with ⓘ links.</summary>
public class ExplanationView : LearningOnlyView
{
    public static readonly BindableProperty ExplanationProperty = BindableProperty.Create(
        nameof(Explanation), typeof(Explanation), typeof(ExplanationView), null,
        propertyChanged: (b, _, _) => ((ExplanationView)b).Build());

    public static readonly BindableProperty AlwaysShowProperty =
        BindableProperty.Create(nameof(AlwaysShow), typeof(bool), typeof(ExplanationView), false,
            propertyChanged: (b, _, _) => ((ExplanationView)b).Refresh());

    public Explanation? Explanation
    {
        get => (Explanation?)GetValue(ExplanationProperty);
        set => SetValue(ExplanationProperty, value);
    }

    /// <summary>True when the user explicitly opened the explanation, so it ignores the Learning switch.</summary>
    public bool AlwaysShow
    {
        get => (bool)GetValue(AlwaysShowProperty);
        set => SetValue(AlwaysShowProperty, value);
    }

    protected override bool ShouldShow => Explanation is not null && (AlwaysShow || LearningMode.Current.IsOn);

    static Color LevelColor(VerdictLevel l) => l switch
    {
        VerdictLevel.Good => Theme.Get("Accent"),
        VerdictLevel.Caution => Theme.Get("Warn"),
        VerdictLevel.Bad => Theme.Get("Danger"),
        _ => Theme.Get("MutedColor"),
    };

    void Build()
    {
        var e = Explanation;
        if (e is null)
        {
            Content = null;
            Refresh();
            return;
        }
        var stack = new VerticalStackLayout { Spacing = 10 };
        if (e.Level != VerdictLevel.None)
        {
            stack.Add(new Border
            {
                BackgroundColor = LevelColor(e.Level).WithAlpha(0.18f),
                Stroke = LevelColor(e.Level),
                StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 8 },
                Padding = new Thickness(10, 6),
                HorizontalOptions = LayoutOptions.Start,
                Content = Theme.Text(e.LevelLabel, color: LevelColor(e.Level)),
            });
        }
        var summary = Theme.Text(e.Summary);
        summary.FontAttributes = FontAttributes.Bold;
        stack.Add(summary);
        foreach (var section in e.Sections)
        {
            var head = new Grid { ColumnDefinitions = { new(GridLength.Star), new(GridLength.Auto) }, Margin = new Thickness(0, 6, 0, 0) };
            head.Add(Theme.Text(section.Heading, "H2"));
            if (section.Term is not null) head.Add(new InfoButton { Term = section.Term }, 1);
            stack.Add(head);
            foreach (var line in section.Lines)
            {
                var row = new Grid { ColumnDefinitions = { new(new GridLength(14)), new(GridLength.Star) } };
                row.Add(Theme.Text(char.IsDigit(line.FirstOrDefault()) ? "" : "•", color: Theme.Get("MutedColor")));
                row.Add(Theme.Text(line), 1);
                stack.Add(row);
            }
        }
        Content = new Border { Style = Theme.Style("Card"), Content = stack };
        Refresh();
    }
}
