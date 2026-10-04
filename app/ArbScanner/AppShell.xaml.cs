using ArbScanner.Services;
using ArbScanner.Views;

namespace ArbScanner;

public partial class AppShell : Shell
{
    readonly Credentials _creds;
    readonly PushRegistration _push;
    bool _checked;

    public AppShell(Credentials creds, PushRegistration push)
    {
        _creds = creds;
        _push = push;
        InitializeComponent();
        Routing.RegisterRoute("opportunity", typeof(OpportunityPage));
        Routing.RegisterRoute("pairs", typeof(PairsPage));
    }

    protected override async void OnAppearing()
    {
        base.OnAppearing();
        if (_checked) return;
        _checked = true;
        await _creds.LoadAsync();
        if (!_creds.IsConfigured)
            await Navigation.PushModalAsync(App.Services.GetRequiredService<SetupPage>());
        else
            _push.Request();
    }
}
