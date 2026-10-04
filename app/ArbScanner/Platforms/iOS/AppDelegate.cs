using ArbScanner.Services;
using Foundation;
using UIKit;
using UserNotifications;

namespace ArbScanner;

[Register("AppDelegate")]
public class AppDelegate : MauiUIApplicationDelegate, IUNUserNotificationCenterDelegate
{
    protected override MauiApp CreateMauiApp() => MauiProgram.CreateMauiApp();

    static PushRegistration Push => App.Services.GetRequiredService<PushRegistration>();

    public override bool FinishedLaunching(UIApplication application, NSDictionary? launchOptions)
    {
        var result = base.FinishedLaunching(application, launchOptions!);
        UNUserNotificationCenter.Current.Delegate = this;
        PushRegistration.RequestPlatformRegistration = () =>
            UNUserNotificationCenter.Current.RequestAuthorization(
                UNAuthorizationOptions.Alert | UNAuthorizationOptions.Sound | UNAuthorizationOptions.Badge,
                (granted, _) =>
                {
                    if (granted)
                        MainThread.BeginInvokeOnMainThread(UIApplication.SharedApplication.RegisterForRemoteNotifications);
                });
        return result;
    }

    [Export("application:didRegisterForRemoteNotificationsWithDeviceToken:")]
    public void DidRegisterForRemoteNotifications(UIApplication application, NSData deviceToken) =>
        Push.OnDeviceToken(Convert.ToHexString(deviceToken.ToArray()).ToLowerInvariant());

    [Export("application:didFailToRegisterForRemoteNotificationsWithError:")]
    public void DidFailToRegisterForRemoteNotifications(UIApplication application, NSError error) =>
        Push.OnRegistrationFailed(error.LocalizedDescription);

    // Show alerts even while the app is open.
    [Export("userNotificationCenter:willPresentNotification:withCompletionHandler:")]
    public void WillPresentNotification(UNUserNotificationCenter center, UNNotification notification,
        Action<UNNotificationPresentationOptions> completionHandler) =>
        completionHandler(UNNotificationPresentationOptions.Banner | UNNotificationPresentationOptions.List |
                          UNNotificationPresentationOptions.Sound);

    // Tapping a notification deep-links to the opportunity.
    [Export("userNotificationCenter:didReceiveNotificationResponse:withCompletionHandler:")]
    public void DidReceiveNotificationResponse(UNUserNotificationCenter center, UNNotificationResponse response,
        Action completionHandler)
    {
        var data = new Dictionary<string, string>();
        foreach (var (key, value) in response.Notification.Request.Content.UserInfo)
            data[key.ToString() ?? ""] = value?.ToString() ?? "";
        PushRegistration.OnNotificationTapped(data);
        completionHandler();
    }
}
