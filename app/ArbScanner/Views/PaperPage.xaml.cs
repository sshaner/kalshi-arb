using ArbScanner.ViewModels;

namespace ArbScanner.Views;

public partial class PaperPage : ContentPage
{
    readonly PaperViewModel _vm;

    public PaperPage(PaperViewModel vm)
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
