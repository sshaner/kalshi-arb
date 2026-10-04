using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ArbScanner.Services;

/// <summary>
/// The on/off switch for every teaching element (intro cards, ⓘ buttons, explanations). Stored on the phone.
/// XAML binds to the single instance via <c>{x:Static services:LearningMode.Current}</c>.
/// </summary>
public partial class LearningMode : ObservableObject
{
    const string OnKey = "learning_on";
    const string TutorialKey = "tutorial_seen";
    const string DismissedKey = "intros_dismissed";

    public static LearningMode Current { get; } = new();

    [ObservableProperty] bool isOn;
    [ObservableProperty] bool tutorialSeen;
    readonly HashSet<string> _dismissed;

    /// <summary>Raised when an intro card is dismissed or intros are reset.</summary>
    public event Action? IntrosChanged;

    LearningMode()
    {
        isOn = Preferences.Default.Get(OnKey, true);
        tutorialSeen = Preferences.Default.Get(TutorialKey, false);
        _dismissed = Preferences.Default.Get(DismissedKey, "")
            .Split(',', StringSplitOptions.RemoveEmptyEntries).ToHashSet();
    }

    public string ToggleText => IsOn ? "Help ✓" : "Help";

    partial void OnIsOnChanged(bool value)
    {
        Preferences.Default.Set(OnKey, value);
        OnPropertyChanged(nameof(ToggleText));
    }

    partial void OnTutorialSeenChanged(bool value) => Preferences.Default.Set(TutorialKey, value);

    [RelayCommand]
    void Toggle() => IsOn = !IsOn;

    public bool IsIntroDismissed(string key) => _dismissed.Contains(key);

    public void DismissIntro(string key)
    {
        _dismissed.Add(key);
        Preferences.Default.Set(DismissedKey, string.Join(',', _dismissed));
        IntrosChanged?.Invoke();
    }

    public void ResetIntros()
    {
        _dismissed.Clear();
        Preferences.Default.Remove(DismissedKey);
        IntrosChanged?.Invoke();
    }
}
