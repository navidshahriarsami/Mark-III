/**
 * Root layout — mounts QueryClient, runs push registration once,
 * and wires foreground notification handlers.
 */

import React, { useEffect } from 'react';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useMarkStore } from '@/store/useMarkStore';
import { requestPermissionsAndRegister, setupNotificationHandlers } from '@/services/push';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 2, staleTime: 10_000 },
  },
});

export default function RootLayout() {
  const setPushToken = useMarkStore((s) => s.setPushToken);

  useEffect(() => {
    // Register for push notifications once on mount
    requestPermissionsAndRegister().then((token) => {
      if (token) setPushToken(token);
    });

    // Wire foreground + tap handlers; clean up on unmount
    const cleanup = setupNotificationHandlers();
    return cleanup;
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <StatusBar style="light" />
      <Stack screenOptions={{ headerShown: false }} />
    </QueryClientProvider>
  );
}
