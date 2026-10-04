namespace ArbScanner.Controls;

/// <summary>Big "8/10 Strong" badge, colored by tier: 7+ green, 5-6 amber, 4 and below grey.</summary>
public class RatingBadge : ContentView
{
    public static readonly BindableProperty RatingProperty = BindableProperty.Create(
        nameof(Rating), typeof(int?), typeof(RatingBadge), null, propertyChanged: (b, _, _) => ((RatingBadge)b).Update());

    public static readonly BindableProperty RatingTextProperty = BindableProperty.Create(
        nameof(RatingText), typeof(string), typeof(RatingBadge), "", propertyChanged: (b, _, _) => ((RatingBadge)b).Update());

    public int? Rating
    {
        get => (int?)GetValue(RatingProperty);
        set => SetValue(RatingProperty, value);
    }

    public string RatingText
    {
        get => (string)GetValue(RatingTextProperty);
        set => SetValue(RatingTextProperty, value);
    }

    readonly Label _number = new() { FontSize = 22, FontAttributes = FontAttributes.Bold, VerticalOptions = LayoutOptions.Center };
    readonly Label _outOf = new() { Text = "/10", FontSize = 12, VerticalOptions = LayoutOptions.Center };
    readonly Label _label = new() { FontSize = 13, FontAttributes = FontAttributes.Bold, VerticalOptions = LayoutOptions.Center, Margin = new Thickness(6, 0, 0, 0) };
    readonly Border _border;

    public RatingBadge()
    {
        _border = new Border
        {
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 10 },
            Padding = new Thickness(10, 2),
            HorizontalOptions = LayoutOptions.Start,
            Content = new HorizontalStackLayout { Spacing = 1, Children = { _number, _outOf, _label } },
        };
        Content = _border;
        Update();
    }

    void Update()
    {
        IsVisible = Rating is not null;
        if (Rating is not int r) return;
        var color = Theme.Get(r >= 7 ? "Accent" : r >= 5 ? "Warn" : "MutedColor");
        _number.Text = r.ToString();
        _number.TextColor = _outOf.TextColor = _label.TextColor = color;
        _label.Text = RatingText;
        _border.Stroke = color;
        _border.BackgroundColor = color.WithAlpha(0.15f);
    }
}
