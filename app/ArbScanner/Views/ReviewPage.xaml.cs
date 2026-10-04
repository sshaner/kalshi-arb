using ArbScanner.ViewModels;

namespace ArbScanner.Views;

public partial class ReviewPage : ContentPage
{
    readonly ReviewViewModel _vm;

    public ReviewPage(ReviewViewModel vm)
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
