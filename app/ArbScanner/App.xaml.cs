using ArbScanner.Services;

namespace ArbScanner;

public partial class App : Application
{
    public static IServiceProvider Services { get; private set; } = default!;

    public App(IServiceProvider services)
    {
        Services = services;
        InitializeComponent();
        UserAppTheme = AppTheme.Dark;
    }

    protected override Window CreateWindow(IActivationState? activationState) =>
        new(Services.GetRequiredService<AppShell>());

    protected override void OnResume()
    {
        base.OnResume();
        // Re-send the device token in case the server lost it (fresh DB, redeploy).
        _ = Services.GetRequiredService<PushRegistration>().TryUploadAsync();
    }
}
