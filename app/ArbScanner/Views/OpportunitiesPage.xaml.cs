using ArbScanner.ViewModels;

namespace ArbScanner.Views;

public partial class OpportunitiesPage : ContentPage
{
    readonly OpportunitiesViewModel _vm;

    public OpportunitiesPage(OpportunitiesViewModel vm)
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
