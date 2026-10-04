using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using ArbScanner.Models;

namespace ArbScanner.Services;

public class ApiException(string message, HttpStatusCode? status = null) : Exception(message)
{
    public HttpStatusCode? Status { get; } = status;
}

/// <summary>Typed client for server/arb/api.py. Base URL + bearer token come from <see cref="Credentials"/>.</summary>
public class ApiClient(Credentials creds)
{
    static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        NumberHandling = System.Text.Json.Serialization.JsonNumberHandling.AllowReadingFromString,
    };

    readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(20) };

    async Task<T> Send<T>(HttpMethod method, string path, object? body = null)
    {
        if (!creds.IsConfigured) throw new ApiException("Server not configured");
        using var req = new HttpRequestMessage(method, creds.BaseUrl!.TrimEnd('/') + path);
        req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", creds.Token);
        if (body is not null) req.Content = JsonContent.Create(body, options: Json);
        HttpResponseMessage res;
        try
        {
            res = await _http.SendAsync(req);
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException)
        {
            throw new ApiException($"Can't reach server: {e.Message}");
        }
        if (res.StatusCode == HttpStatusCode.Unauthorized) throw new ApiException("Token rejected by server", res.StatusCode);
        if (!res.IsSuccessStatusCode) throw new ApiException($"Server error {(int)res.StatusCode}", res.StatusCode);
        return (await res.Content.ReadFromJsonAsync<T>(Json))!;
    }

    public Task<ServerStatus> Status() => Send<ServerStatus>(HttpMethod.Get, "/api/status");

    public Task<List<Opportunity>> Opportunities(bool active = true) =>
        Send<List<Opportunity>>(HttpMethod.Get, $"/api/opportunities?active={(active ? "true" : "false")}");

    public Task<Opportunity> Opportunity(long id) => Send<Opportunity>(HttpMethod.Get, $"/api/opportunities/{id}");

    public Task<List<Candidate>> Candidates() => Send<List<Candidate>>(HttpMethod.Get, "/api/candidates?limit=200");

    public Task<Pair> Approve(long id, bool inverted, string notes) =>
        Send<Pair>(HttpMethod.Post, $"/api/candidates/{id}/approve", new { inverted, notes });

    public Task<JsonElement> Reject(long id) => Send<JsonElement>(HttpMethod.Post, $"/api/candidates/{id}/reject");

    public Task<JsonElement> RunDiscovery() => Send<JsonElement>(HttpMethod.Post, "/api/discovery/run");

    public Task<List<Pair>> Pairs() => Send<List<Pair>>(HttpMethod.Get, "/api/pairs");

    public Task<Pair> UpdatePair(long id, bool? paused = null, bool? inverted = null, string? notes = null) =>
        Send<Pair>(HttpMethod.Patch, $"/api/pairs/{id}", new { paused, inverted, notes });

    public Task<JsonElement> RemovePair(long id) => Send<JsonElement>(HttpMethod.Delete, $"/api/pairs/{id}");

    public Task<List<PaperPosition>> Positions(string status) =>
        Send<List<PaperPosition>>(HttpMethod.Get, $"/api/paper/positions?status={status}");

    public Task<PaperSummary> PaperSummary() => Send<PaperSummary>(HttpMethod.Get, "/api/paper/summary");

    public Task<ScannerSettings> Settings() => Send<ScannerSettings>(HttpMethod.Get, "/api/settings");

    public Task<ScannerSettings> SaveSettings(ScannerSettings s) => Send<ScannerSettings>(HttpMethod.Put, "/api/settings", s);

    public Task<JsonElement> RegisterDevice(string token) => Send<JsonElement>(HttpMethod.Post, "/api/devices", new { token });

    public Task<PushTestResult> TestPush() => Send<PushTestResult>(HttpMethod.Post, "/api/push/test");
}
