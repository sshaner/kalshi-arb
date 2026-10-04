using ArbScanner.ViewModels;

namespace ArbScanner.Views;

public partial class DashboardPage : ContentPage
{
    readonly DashboardViewModel _vm;
    IDispatcherTimer? _timer;

    public DashboardPage(DashboardViewModel vm)
    {
        InitializeComponent();
        BindingContext = _vm = vm;
    }

    protected override void OnAppearing()
    {
        base.OnAppearing();
        _vm.RefreshCommand.Execute(null);
        _timer ??= Dispatcher.CreateTimer();
        _timer.Interval = TimeSpan.FromSeconds(15);
        _timer.Tick += Tick;
        _timer.Start();
    }

    protected override void OnDisappearing()
    {
        base.OnDisappearing();
        if (_timer is null) return;
        _timer.Stop();
        _timer.Tick -= Tick;
    }

    void Tick(object? sender, EventArgs e) => _vm.PollCommand.Execute(null);
}
