using System.Collections.ObjectModel;
using ArbScanner.Learning;
using ArbScanner.Models;
using ArbScanner.Services;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ArbScanner.ViewModels;

public partial class BaseViewModel : ObservableObject
{
    [ObservableProperty] bool isBusy;
    [ObservableProperty] string? error;

    protected async Task Run(Func<Task> work)
    {
        if (IsBusy) return;
        IsBusy = true;
        Error = null;
        try { await work(); }
        catch (Exception e) { Error = e.Message; }
        finally { IsBusy = false; }
    }

    protected static Task Alert(string title, string message) =>
        Shell.Current?.DisplayAlertAsync(title, message, "OK") ?? Task.CompletedTask;

    protected static Task<bool> Confirm(string title, string message, string accept) =>
        Shell.Current?.DisplayAlertAsync(title, message, accept, "Cancel") ?? Task.FromResult(false);
}

// ---------------------------------------------------------------------------------------------
public partial class SetupViewModel(ApiClient api, Credentials creds, PushRegistration push) : BaseViewModel
{
    [ObservableProperty] string url = Credentials.DefaultUrl;
    [ObservableProperty] string token = "";

    public event Action? Connected;

    [RelayCommand]
    Task Connect() => Run(async () =>
    {
        if (string.IsNullOrWhiteSpace(Url) || string.IsNullOrWhiteSpace(Token))
            throw new InvalidOperationException("Enter the server URL and token.");
        var oldUrl = creds.BaseUrl;
        var oldToken = creds.Token;
        await creds.SaveAsync(Url, Token);
        try
        {
            await api.Status();
        }
        catch
        {
            if (oldUrl is not null && oldToken is not null) await creds.SaveAsync(oldUrl, oldToken);
            else creds.Clear();
            throw;
        }
        push.Request();
        await push.TryUploadAsync();
        Connected?.Invoke();
    });
}

// ---------------------------------------------------------------------------------------------
public record BestReturn(string Title, string Detail, string Badge, long? OpportunityId);

public partial class DashboardViewModel(ApiClient api) : BaseViewModel
{
    [ObservableProperty] ServerStatus? status;
    public ObservableCollection<BestReturn> BestReturns { get; } = new();
    [ObservableProperty] string bestReturnsCaption = "";

    /// <summary>Top 3 by yearly return: live opportunities if there are any, else review pairs (6+, gap now).</summary>
    async Task LoadBestReturns()
    {
        var items = new List<BestReturn>();
        var opps = await api.Opportunities(true, "annualized", 3);
        if (opps.Count > 0)
        {
            BestReturnsCaption = "Live opportunities, highest yearly return first. Tap one for the full walkthrough.";
            items.AddRange(opps.Select(o => new BestReturn(o.Title, $"{o.ReturnDisplay} · ${o.Profit:0.00} on {o.Contracts:0}",
                o.Rating is int r ? $"{r}/10" : "", o.Id)));
        }
        else
        {
            BestReturnsCaption = "No live opportunities, so these are review pairs (rated 6+, gap at last-scan prices) with the highest yearly return. Approve the real ones so the scanner watches them.";
            var f = new ReviewFilter { Sort = "annualized", HasGap = true, MinRating = 6 };
            var pairs = await api.Candidates(f, 0, 3);
            items.AddRange(pairs.Select(c => new BestReturn(c.Kalshi?.Display ?? c.KalshiId, c.ReturnDisplay,
                c.Rating is int r ? $"{r}/10" : "", null)));
        }
        BestReturns.Clear();
        foreach (var i in items) BestReturns.Add(i);
        if (items.Count == 0) BestReturnsCaption = "Nothing with a positive return right now.";
    }

    [RelayCommand]
    async Task OpenBestReturn(BestReturn b)
    {
        if (b.OpportunityId is long id)
            await Shell.Current.GoToAsync($"//opportunities/opportunity?id={id}");
        else
            await SeeAllBestReturns();
    }

    [RelayCommand]
    async Task SeeAllBestReturns()
    {
        App.Services.GetRequiredService<ReviewViewModel>().ShowBestReturns();
        await Shell.Current.GoToAsync("//review");
    }

    public string ScannerState => Status is null ? "–" : Status.Settings.ScanEnabled ? "Scanning" : "Paused";
    public string LiveOpps => Status is null ? "–" : Status.Counts.LiveOpportunities.ToString();
    public string BestEdge => Status?.Counts.BestEdgeCents is double e ? $"{e:0.#}¢" : "–";
    public string Pending => Status is null ? "–" : Status.Counts.PendingCandidates.ToString();
    public string Pairs => Status is null ? "–" : Status.Counts.ActivePairs.ToString();
    public string PaperOpen => Status is null ? "–" : $"{Status.Paper.OpenCount} open · ${Status.Paper.OpenCapital:0} deployed";
    public string PaperExpected => Status is null ? "–" : $"+${Status.Paper.OpenExpectedPnl:0.00} expected";
    public string PaperRealized => Status is null ? "–" : $"${Status.Paper.RealizedPnl:0.00} realized · {Status.Paper.SettledCount} settled";
    public string Divergent => Status is null ? "" : Status.Paper.DivergentCount > 0 ? $"⚠︎ {Status.Paper.DivergentCount} divergent resolutions" : "";
    public string DiscoveryLine => Status is null ? "" :
        $"Discovery {Fmt.Ago(Status.Discovery.LastRun)} · {Status.Discovery.KalshiMarkets:N0} Kalshi / {Status.Discovery.PmusMarkets:N0} PM US markets" +
        (Status.Discovery.Running ? " · running" : "");
    public string PricesLine => Status is null ? "" :
        $"Prices {Fmt.Ago(Status.Prices.LastRun)} · {Status.Prices.Pairs} pairs in {Status.Prices.Duration ?? 0:0.0}s";
    public string PushLine => Status is null ? "" :
        Status.Push.Enabled ? $"Push on · {Status.Counts.Devices} device(s)" : "Push not configured on server";
    public string ServerErrors => Status is null ? "" : string.Join("\n",
        new[] { Status.Discovery.Error, Status.Prices.Error, Status.Settlement.Error, Status.Push.LastError }
            .Where(e => !string.IsNullOrEmpty(e)));

    public string LiveHint => Status is null ? "" : Status.Counts.LiveOpportunities > 0
        ? "Arbs available now. Open the Opps tab for the walkthrough."
        : Status.Counts.ActivePairs == 0 ? "None yet: nothing is being watched until you approve pairs in Review."
        : "None right now. Normal; you'll get a push when one appears.";
    public string EdgeHint => "Profit per contract after fees. Under 2¢ is fragile.";
    public string ReviewHint => Status is { Counts.PendingCandidates: > 0 } ? "Start here: approve real matches, reject the rest." : "All caught up.";
    public string PairsHint => "Pairs the scanner checks every ~30 s.";

    partial void OnStatusChanged(ServerStatus? value) => OnPropertyChanged(string.Empty);

    [RelayCommand]
    Task Refresh() => Run(async () =>
    {
        Status = await api.Status();
        await LoadBestReturns();
    });

    /// <summary>Background refresh for the auto-poll timer: no spinner, keeps the last good status on error.</summary>
    [RelayCommand]
    async Task Poll()
    {
        if (IsBusy) return;
        try { Status = await api.Status(); Error = null; }
        catch (Exception e) { Error = e.Message; }
    }

    [RelayCommand]
    Task ToggleScanning() => Run(async () =>
    {
        var s = await api.Settings();
        s.ScanEnabled = !s.ScanEnabled;
        await api.SaveSettings(s);
        Status = await api.Status();
    });
}

// ---------------------------------------------------------------------------------------------
public partial class OpportunitiesViewModel(ApiClient api) : BaseViewModel
{
    public ObservableCollection<Opportunity> Items { get; } = new();
    [ObservableProperty] bool showActive = true;
    [ObservableProperty] int sortIndex;

    public static IReadOnlyList<(string Value, string Label)> SortOptions { get; } = new[]
    {
        ("rating", "Best rating"), ("annualized", "Highest yearly return"), ("roi", "Highest return %"), ("profit", "Most dollars"),
    };

    public List<string> SortLabels { get; } = SortOptions.Select(o => o.Label).ToList();

    partial void OnSortIndexChanged(int value) => RefreshCommand.Execute(null);
    [ObservableProperty] bool isEmpty;

    partial void OnShowActiveChanged(bool value) => RefreshCommand.Execute(null);

    [RelayCommand]
    Task Refresh() => Run(async () =>
    {
        var list = await api.Opportunities(ShowActive, SortOptions[Math.Clamp(SortIndex, 0, SortOptions.Count - 1)].Value);
        var s = await api.SettingsCached();
        Items.Clear();
        foreach (var o in list)
        {
            o.Explanation = Explainer.ExplainOpportunity(o, s);
            Items.Add(o);
        }
        IsEmpty = Items.Count == 0;
    });

    [RelayCommand]
    Task Open(Opportunity o) => Shell.Current.GoToAsync($"opportunity?id={o.Id}");
}

// ---------------------------------------------------------------------------------------------
public partial class OpportunityDetailViewModel(ApiClient api) : BaseViewModel, IQueryAttributable
{
    [ObservableProperty] Opportunity? item;
    public ObservableCollection<string> KalshiBook { get; } = new();
    public ObservableCollection<string> PmusBook { get; } = new();
    long _id;

    public void ApplyQueryAttributes(IDictionary<string, object> query)
    {
        if (query.TryGetValue("id", out var v) && long.TryParse(v?.ToString(), out var id))
        {
            _id = id;
            RefreshCommand.Execute(null);
        }
    }

    [RelayCommand]
    Task Refresh() => Run(async () =>
    {
        var o = await api.Opportunity(_id);
        o.Explanation = Explainer.ExplainOpportunity(o, await api.SettingsCached());
        Item = o;
        Fill(KalshiBook, Item.KBook, Item.KSide);
        Fill(PmusBook, Item.PBook, Item.PSide);
    });

    static void Fill(ObservableCollection<string> target, BookView? book, string side)
    {
        target.Clear();
        var levels = side == "yes" ? book?.YesAsks : book?.NoAsks;
        foreach (var l in (levels ?? new()).Take(6))
            if (l.Count >= 2) target.Add($"{side.ToUpper()} ask {l[0] * 100:0.#}¢ × {l[1]:N0}");
    }

    [RelayCommand]
    Task OpenKalshi() => OpenUrl(Item?.Pair?.Kalshi?.Url);

    [RelayCommand]
    Task OpenPmus() => OpenUrl(Item?.Pair?.Pmus?.Url);

    static async Task OpenUrl(string? url)
    {
        if (!string.IsNullOrEmpty(url)) await Launcher.Default.OpenAsync(new Uri(url));
    }
}

// ---------------------------------------------------------------------------------------------
public partial class ReviewViewModel : BaseViewModel
{
    const string FilterKey = "review_filter";
    const int PageSize = 50;
    readonly ApiClient api;
    int _offset;
    bool _hasMore;
    bool _loadingMore;
    CancellationTokenSource? _searchCts;

    public ReviewViewModel(ApiClient api)
    {
        this.api = api;
        filter = LoadFilter();
        searchText = filter.Query;
    }

    public ObservableCollection<Candidate> Items { get; } = new();
    [ObservableProperty] bool isEmpty;
    [ObservableProperty] ReviewFilter filter;
    [ObservableProperty] string searchText;
    [ObservableProperty] string showingText = "";

    public string FiltersButtonText => Filter.ActiveCount == 0 ? "Filters" : $"Filters ({Filter.ActiveCount})";
    public string QuickReturnText => (Filter.SortsByReturn ? "✓ " : "") + "Best return";
    public string QuickTopText => (Filter.MinRating >= 8 ? "✓ " : "") + "Rated 8+";
    public string QuickGapText => (Filter.HasGap ? "✓ " : "") + "Gap now";
    public string QuickSoonText => (Filter.ClosesWithinDays is <= 1 ? "✓ " : "") + "Closes ≤24h";

    static ReviewFilter LoadFilter()
    {
        try
        {
            var json = Preferences.Default.Get(FilterKey, "");
            return string.IsNullOrEmpty(json) ? new ReviewFilter() : System.Text.Json.JsonSerializer.Deserialize<ReviewFilter>(json) ?? new();
        }
        catch { return new ReviewFilter(); }
    }

    void Apply(ReviewFilter f)
    {
        Filter = f;
        Preferences.Default.Set(FilterKey, System.Text.Json.JsonSerializer.Serialize(f));
        OnPropertyChanged(nameof(FiltersButtonText));
        OnPropertyChanged(nameof(QuickTopText));
        OnPropertyChanged(nameof(QuickReturnText));
        OnPropertyChanged(nameof(QuickGapText));
        OnPropertyChanged(nameof(QuickSoonText));
        RefreshCommand.Execute(null);
    }

    partial void OnSearchTextChanged(string value)
    {
        // Debounce typing: search half a second after the last keystroke.
        _searchCts?.Cancel();
        var cts = _searchCts = new CancellationTokenSource();
        _ = Task.Delay(500, cts.Token).ContinueWith(t =>
        {
            if (t.IsCanceled || value == Filter.Query) return;
            MainThread.BeginInvokeOnMainThread(() =>
            {
                var f = Filter.Clone();
                f.Query = value ?? "";
                Apply(f);
            });
        }, TaskScheduler.Default);
    }

    [RelayCommand]
    Task OpenFilters() => Shell.Current.Navigation.PushModalAsync(new Views.FilterPage(Filter, Apply));

    [RelayCommand]
    void ToggleTop() => Apply(With(f => f.MinRating = f.MinRating >= 8 ? 1 : 8));

    /// <summary>Highest yearly return first, limited to trustworthy pairs (6+) that have a real gap now.</summary>
    [RelayCommand]
    void ToggleReturn() => Apply(With(f =>
    {
        if (f.SortsByReturn)
        {
            f.Sort = "rating";
            f.HasGap = false;
            if (f.MinRating == 6) f.MinRating = 1;
        }
        else
        {
            f.Sort = "annualized";
            f.HasGap = true;
            f.MinRating = Math.Max(f.MinRating, 6);
        }
    }));

    /// <summary>Used by the Dashboard's "see all" link.</summary>
    public void ShowBestReturns() => Apply(With(f =>
    {
        f.Sort = "annualized";
        f.HasGap = true;
        f.MinRating = Math.Max(f.MinRating, 6);
    }));

    [RelayCommand]
    void ToggleGap() => Apply(With(f => f.HasGap = !f.HasGap));

    [RelayCommand]
    void ToggleSoon() => Apply(With(f => f.ClosesWithinDays = f.ClosesWithinDays is <= 1 ? null : 1));

    ReviewFilter With(Action<ReviewFilter> change)
    {
        var f = Filter.Clone();
        change(f);
        return f;
    }

    [RelayCommand]
    Task Refresh() => Run(async () =>
    {
        var countTask = api.CandidateCount(Filter);
        var list = await api.Candidates(Filter, 0, PageSize);
        var s = await api.SettingsCached();
        Items.Clear();
        AddPage(list, s);
        _offset = list.Count;
        _hasMore = list.Count == PageSize;
        var count = await countTask;
        ShowingText = Filter.ActiveCount == 0 && string.IsNullOrWhiteSpace(Filter.Query)
            ? $"{count.Total:N0} pairs to review"
            : $"{count.Matching:N0} of {count.Total:N0} pairs · {Filter.Describe()}";
        IsEmpty = Items.Count == 0;
    });

    [RelayCommand]
    async Task LoadMore()
    {
        if (!_hasMore || _loadingMore || IsBusy) return;
        _loadingMore = true;
        try
        {
            var list = await api.Candidates(Filter, _offset, PageSize);
            AddPage(list, await api.SettingsCached());
            _offset += list.Count;
            _hasMore = list.Count == PageSize;
        }
        catch (Exception e) { Error = e.Message; }
        finally { _loadingMore = false; }
    }

    void AddPage(List<Candidate> list, ScannerSettings s)
    {
        foreach (var c in list)
        {
            c.Explanation = Explainer.ExplainCandidate(c, s);
            Items.Add(c);
        }
    }

    [RelayCommand]
    async Task Approve(Candidate c)
    {
        var notes = await Shell.Current.DisplayPromptAsync("Approve pair",
            "Same outcome on both venues? Note any resolution differences (optional).", "Approve", "Cancel",
            placeholder: "notes", maxLength: 300);
        if (notes is null) return;
        await Run(async () => { await api.Approve(c.Id, false, notes); Items.Remove(c); IsEmpty = Items.Count == 0; });
    }

    [RelayCommand]
    async Task ApproveInverted(Candidate c)
    {
        if (!await Confirm("Approve as inverted",
                "Kalshi YES = Polymarket NO for this pair (e.g. opposite teams). Continue?", "Approve")) return;
        await Run(async () => { await api.Approve(c.Id, true, "inverted"); Items.Remove(c); IsEmpty = Items.Count == 0; });
    }

    [RelayCommand]
    Task Reject(Candidate c) => Run(async () => { await api.Reject(c.Id); Items.Remove(c); IsEmpty = Items.Count == 0; });

    [RelayCommand]
    Task Rules(Candidate c) => Alert("Resolution rules",
        $"KALSHI\n{c.Kalshi?.Rules}\n\nPOLYMARKET US\n{c.Pmus?.Rules}");

    [RelayCommand]
    async Task Explain(Candidate c)
    {
        if (c.Explanation is null) return;
        await Shell.Current.Navigation.PushModalAsync(new Views.ExplanationPage(c.Explanation, "Resolution rules, side by side",
            $"KALSHI\n{c.Kalshi?.Rules}\n\nPOLYMARKET US\n{c.Pmus?.Rules}"));
    }

    [RelayCommand]
    Task Discover() => Run(async () =>
    {
        await api.RunDiscovery();
        await Alert("Discovery started", "New candidates appear here in a minute or two.");
    });

    [RelayCommand]
    Task Pairs() => Shell.Current.GoToAsync("pairs");
}

// ---------------------------------------------------------------------------------------------
public partial class PairsViewModel(ApiClient api) : BaseViewModel
{
    public ObservableCollection<Pair> Items { get; } = new();
    [ObservableProperty] bool isEmpty;

    [RelayCommand]
    Task Refresh() => Run(async () =>
    {
        var list = await api.Pairs();
        Items.Clear();
        foreach (var p in list) Items.Add(p);
        IsEmpty = Items.Count == 0;
    });

    [RelayCommand]
    async Task Manage(Pair p)
    {
        var action = await Shell.Current.DisplayActionSheetAsync(p.Title, "Cancel", "Remove pair",
            p.Paused ? "Resume" : "Pause", p.Inverted ? "Mark not inverted" : "Mark inverted", "Rules");
        switch (action)
        {
            case "Pause":
            case "Resume":
                await Run(async () => { await api.UpdatePair(p.Id, paused: !p.Paused); });
                break;
            case "Mark inverted":
            case "Mark not inverted":
                await Run(async () => { await api.UpdatePair(p.Id, inverted: !p.Inverted); });
                break;
            case "Remove pair":
                if (await Confirm("Remove pair", "Stop scanning this pair?", "Remove"))
                    await Run(async () => { await api.RemovePair(p.Id); });
                break;
            case "Rules":
                await Alert("Resolution rules", $"KALSHI\n{p.Kalshi?.Rules}\n\nPOLYMARKET US\n{p.Pmus?.Rules}\n\nNOTES\n{p.Notes}");
                return;
            default:
                return;
        }
        await Refresh();
    }
}

// ---------------------------------------------------------------------------------------------
public partial class PaperViewModel(ApiClient api) : BaseViewModel
{
    public ObservableCollection<PaperPosition> Items { get; } = new();
    [ObservableProperty] PaperSummary? summary;
    [ObservableProperty] bool showOpen = true;
    [ObservableProperty] bool isEmpty;

    public string Headline => Summary is null ? "–" : $"${Summary.RealizedPnl:0.00}";
    public string Subline => Summary is null ? "" :
        $"{Summary.SettledCount} settled · {Summary.OpenCount} open (${Summary.OpenCapital:0} deployed, +${Summary.OpenExpectedPnl:0.00} expected)";
    public string DivergentLine => Summary is { DivergentCount: > 0 } s ? $"⚠︎ {s.DivergentCount} divergent resolution(s)" : "";

    partial void OnSummaryChanged(PaperSummary? value)
    {
        OnPropertyChanged(nameof(Headline));
        OnPropertyChanged(nameof(Subline));
        OnPropertyChanged(nameof(DivergentLine));
    }

    partial void OnShowOpenChanged(bool value) => RefreshCommand.Execute(null);

    [RelayCommand]
    async Task Explain(PaperPosition p)
    {
        if (p.Explanation is not null)
            await Shell.Current.Navigation.PushModalAsync(new Views.ExplanationPage(p.Explanation));
    }

    [RelayCommand]
    Task Refresh() => Run(async () =>
    {
        Summary = await api.PaperSummary();
        var list = await api.Positions(ShowOpen ? "open" : "settled");
        Items.Clear();
        foreach (var p in list)
        {
            p.Explanation = Explainer.ExplainPosition(p);
            Items.Add(p);
        }
        IsEmpty = Items.Count == 0;
    });
}

// ---------------------------------------------------------------------------------------------
public partial class SettingsViewModel(ApiClient api, Credentials creds, PushRegistration push) : BaseViewModel
{
    [ObservableProperty] bool scanEnabled;
    [ObservableProperty] string minEdgeCents = "";
    [ObservableProperty] string minProfitDollars = "";
    [ObservableProperty] string minAnnualizedPct = "";
    [ObservableProperty] string paperMaxStake = "";
    [ObservableProperty] string alertCooldownMin = "";
    [ObservableProperty] string quietStart = "";
    [ObservableProperty] string quietEnd = "";
    [ObservableProperty] string matchMinScore = "";
    [ObservableProperty] string matchWindowDays = "";
    [ObservableProperty] string pushInfo = "";
    ScannerSettings? _loaded;

    public string ServerUrl => creds.BaseUrl ?? "";

    [RelayCommand]
    Task Refresh() => Run(async () =>
    {
        var s = _loaded = await api.Settings();
        ScanEnabled = s.ScanEnabled;
        MinEdgeCents = s.MinEdgeCents.ToString("0.##");
        MinProfitDollars = s.MinProfitDollars.ToString("0.##");
        MinAnnualizedPct = (s.MinAnnualized * 100).ToString("0.##");
        PaperMaxStake = s.PaperMaxStake.ToString("0.##");
        AlertCooldownMin = s.AlertCooldownMin.ToString("0");
        QuietStart = s.QuietHoursStart?.ToString() ?? "";
        QuietEnd = s.QuietHoursEnd?.ToString() ?? "";
        MatchMinScore = s.MatchMinScore.ToString("0");
        MatchWindowDays = s.MatchDateWindowDays.ToString("0.#");
        PushInfo = push.DeviceToken is null
            ? $"This device isn't registered for push yet.{(push.LastError is null ? "" : " " + push.LastError)}"
            : "This device is registered for push.";
        OnPropertyChanged(nameof(ServerUrl));
    });

    static double Num(string text, string field) =>
        double.TryParse(text, out var v) ? v : throw new FormatException($"{field} must be a number");

    static int? Hour(string text, string field)
    {
        if (string.IsNullOrWhiteSpace(text)) return null;
        return int.TryParse(text, out var h) && h is >= 0 and <= 23 ? h : throw new FormatException($"{field} must be 0–23");
    }

    [RelayCommand]
    Task Save() => Run(async () =>
    {
        var s = _loaded ?? new ScannerSettings();
        s.ScanEnabled = ScanEnabled;
        s.MinEdgeCents = Num(MinEdgeCents, "Min edge");
        s.MinProfitDollars = Num(MinProfitDollars, "Min profit");
        s.MinAnnualized = Num(MinAnnualizedPct, "Min annualized") / 100;
        s.PaperMaxStake = Num(PaperMaxStake, "Max stake");
        s.AlertCooldownMin = Num(AlertCooldownMin, "Alert cooldown");
        s.QuietHoursStart = Hour(QuietStart, "Quiet start");
        s.QuietHoursEnd = Hour(QuietEnd, "Quiet end");
        s.MatchMinScore = Num(MatchMinScore, "Match score");
        s.MatchDateWindowDays = Num(MatchWindowDays, "Date window");
        _loaded = await api.SaveSettings(s);
        await Alert("Saved", "Settings updated on the server.");
    });

    [RelayCommand]
    Task TestPush() => Run(async () =>
    {
        push.Request();
        await push.TryUploadAsync();
        var r = await api.TestPush();
        await Alert("Test push", r.Enabled
            ? $"Sent to {r.Sent} device(s).{(r.LastError is null ? "" : "\n" + r.LastError)}"
            : "APNs isn't configured on the server yet.");
    });

    [RelayCommand]
    Task ReplayTutorial() => Shell.Current.Navigation.PushModalAsync(new Views.TutorialPage());

    [RelayCommand]
    Task OpenGlossary() => Shell.Current.Navigation.PushModalAsync(new Views.GlossaryPage());

    [RelayCommand]
    Task ResetIntros()
    {
        Services.LearningMode.Current.ResetIntros();
        return Alert("Intro cards restored", "Each screen's intro card will show again while Learning mode is on.");
    }

    [RelayCommand]
    async Task SignOut()
    {
        if (!await Confirm("Sign out", "Forget the server URL and token on this phone?", "Sign out")) return;
        creds.Clear();
        await Shell.Current.Navigation.PushModalAsync(App.Services.GetRequiredService<Views.SetupPage>());
    }
}
