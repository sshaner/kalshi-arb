using ArbScanner.ViewModels;

namespace ArbScanner.Views;

public partial class OpportunityPage : ContentPage
{
    public OpportunityPage(OpportunityDetailViewModel vm)
    {
        InitializeComponent();
        BindingContext = vm;
    }
}
