/**
 * MARK III Mobile — Push Notification Service
 *
 * Handles Expo / FCM token registration and incoming notification routing.
 *
 * Flow:
 *   1. App boots → requestPermissionsAndRegister() called once.
 *   2. Gets Expo push token (wraps FCM token on Android, APNs on iOS).
 *   3. POSTs token to brain server via api.registerPushToken().
 *   4. Brain server stores token and uses it for FCM fan-out on breach alerts.
 *   5. setupNotificationHandlers() wires foreground + background tap handlers.
 */

import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';
import { api } from '@/services/api';
import { useMarkStore } from '@/store/useMarkStore';

// Show alerts as banners even when the app is in the foreground
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge:  false,
  }),
});

// ---------------------------------------------------------------------------
// Permission + token registration
// ---------------------------------------------------------------------------

export async function requestPermissionsAndRegister(): Promise<string | null> {
  if (!Device.isDevice) {
    console.warn('[push] Running in simulator — push tokens not available.');
    return null;
  }

  const { status: existing } = await Notifications.getPermissionsAsync();
  let finalStatus = existing;

  if (existing !== 'granted') {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }

  if (finalStatus !== 'granted') {
    console.warn('[push] Push notification permission denied.');
    return null;
  }

  // Android channel
  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('markiii', {
      name:       'MARK III Alerts',
      importance: Notifications.AndroidImportance.HIGH,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: '#00C896',
    });
  }

  let token: string;
  try {
    // projectId is required in SDK 51; falls back to Expo Go's own project ID
    const tokenData = await Notifications.getExpoPushTokenAsync({
      projectId: 'markiii-mobile',
    });
    token = tokenData.data;
  } catch (err) {
    console.warn('[push] getExpoPushTokenAsync failed:', err);
    return null;
  }

  // Register with brain server
  try {
    await api.registerPushToken({
      mobile_device_id: Device.modelName ?? 'unknown',
      expo_push_token:  token,
      platform:         Platform.OS,
    });
    console.info('[push] Token registered with brain server.');
  } catch (err) {
    console.warn('[push] Failed to register token with brain server:', err);
  }

  return token;
}

// ---------------------------------------------------------------------------
// Notification handlers
// ---------------------------------------------------------------------------

export function setupNotificationHandlers(): () => void {
  // Foreground notification received — update store so dashboard reflects it
  const foregroundSub = Notifications.addNotificationReceivedListener(notification => {
    const { title, body } = notification.request.content;
    console.info('[push] Foreground notification:', title, body);
    useMarkStore.getState().setLastNotification({ title: title ?? '', body: body ?? '' });
  });

  // User tapped a notification — could route to a specific tab in the future
  const responseSub = Notifications.addNotificationResponseReceivedListener(response => {
    const data = response.notification.request.content.data;
    console.info('[push] Notification tapped. data:', data);
    // TODO: deep-link to breach log or sudo approval modal based on data.type
  });

  return () => {
    foregroundSub.remove();
    responseSub.remove();
  };
}
