using ArbScanner.ViewModels;

namespace ArbScanner.Views;

public partial class SetupPage : ContentPage
{
    public SetupPage(SetupViewModel vm)
    {
        InitializeComponent();
        BindingContext = vm;
        vm.Connected += async () =>
        {
            await Navigation.PopModalAsync();
            App.Services.GetRequiredService<DashboardViewModel>().RefreshCommand.Execute(null);
            if (!Services.LearningMode.Current.TutorialSeen)
                await Shell.Current.Navigation.PushModalAsync(new TutorialPage());
        };
    }

    // Setup is mandatory; swallow the Android back button.
    protected override bool OnBackButtonPressed() => true;
}
