namespace ArbScanner.Services;

/// <summary>
/// Bridges the platform push layer (AppDelegate on iOS) to the server and the UI.
/// The platform code calls <see cref="OnDeviceToken"/> and <see cref="OnNotificationTapped"/>.
/// </summary>
public class PushRegistration(ApiClient api, Credentials creds)
{
    public string? DeviceToken { get; private set; }
    public string? LastError { get; private set; }

    /// <summary>Set by the platform layer; asks iOS for permission and a device token.</summary>
    public static Action? RequestPlatformRegistration { get; set; }

    public void Request() => RequestPlatformRegistration?.Invoke();

    public async void OnDeviceToken(string hexToken)
    {
        DeviceToken = hexToken;
        await TryUploadAsync();
    }

    public void OnRegistrationFailed(string error) => LastError = error;

    public async Task TryUploadAsync()
    {
        if (DeviceToken is null || !creds.IsConfigured) return;
        try
        {
            await api.RegisterDevice(DeviceToken);
            LastError = null;
        }
        catch (Exception e)
        {
            LastError = e.Message;
        }
    }

    public static void OnNotificationTapped(IDictionary<string, string> data)
    {
        if (data.TryGetValue("opp_id", out var id) && long.TryParse(id, out _))
        {
            MainThread.BeginInvokeOnMainThread(async () =>
            {
                if (Shell.Current is not null)
                    await Shell.Current.GoToAsync($"//opportunities/opportunity?id={id}");
            });
        }
    }
}
