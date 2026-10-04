namespace ArbScanner.Services;

/// <summary>Server URL + API token, kept in the iOS Keychain via SecureStorage.</summary>
public class Credentials
{
    const string UrlKey = "server_url";
    const string TokenKey = "api_token";
    public const string DefaultUrl = "https://arb.shnr.org";

    public string? BaseUrl { get; private set; }
    public string? Token { get; private set; }
    public bool IsConfigured => !string.IsNullOrWhiteSpace(BaseUrl) && !string.IsNullOrWhiteSpace(Token);

    public async Task LoadAsync()
    {
        try
        {
            BaseUrl = await SecureStorage.Default.GetAsync(UrlKey);
            Token = await SecureStorage.Default.GetAsync(TokenKey);
        }
        catch
        {
            // Keychain can fail right after a reinstall; treat as signed out.
            BaseUrl = Token = null;
        }
    }

    public async Task SaveAsync(string url, string token)
    {
        BaseUrl = url.Trim().TrimEnd('/');
        Token = token.Trim();
        await SecureStorage.Default.SetAsync(UrlKey, BaseUrl);
        await SecureStorage.Default.SetAsync(TokenKey, Token);
    }

    public void Clear()
    {
        SecureStorage.Default.Remove(UrlKey);
        SecureStorage.Default.Remove(TokenKey);
        BaseUrl = Token = null;
    }
}
