using ArbScanner.Services;
using ArbScanner.ViewModels;
using ArbScanner.Views;

namespace ArbScanner;

public static class MauiProgram
{
    public static MauiApp CreateMauiApp()
    {
        var builder = MauiApp.CreateBuilder();
        builder.UseMauiApp<App>();

        builder.Services.AddSingleton<Credentials>();
        builder.Services.AddSingleton<ApiClient>();
        builder.Services.AddSingleton<PushRegistration>();

        builder.Services.AddSingleton<AppShell>();
        builder.Services.AddTransient<SetupPage>().AddTransient<SetupViewModel>();
        builder.Services.AddSingleton<DashboardPage>().AddSingleton<DashboardViewModel>();
        builder.Services.AddSingleton<OpportunitiesPage>().AddSingleton<OpportunitiesViewModel>();
        builder.Services.AddTransient<OpportunityPage>().AddTransient<OpportunityDetailViewModel>();
        builder.Services.AddSingleton<ReviewPage>().AddSingleton<ReviewViewModel>();
        builder.Services.AddTransient<PairsPage>().AddTransient<PairsViewModel>();
        builder.Services.AddSingleton<PaperPage>().AddSingleton<PaperViewModel>();
        builder.Services.AddSingleton<SettingsPage>().AddSingleton<SettingsViewModel>();

        return builder.Build();
    }
}
