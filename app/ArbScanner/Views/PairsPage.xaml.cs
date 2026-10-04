using ArbScanner.ViewModels;

namespace ArbScanner.Views;

public partial class PairsPage : ContentPage
{
    readonly PairsViewModel _vm;

    public PairsPage(PairsViewModel vm)
    {
        InitializeComponent();
        BindingContext = _vm = vm;
    }

    protected override void OnAppearing()
    {
        base.OnAppearing();
        _vm.RefreshCommand.Execute(null);
    }
}
