import React from 'react';
import { Tabs } from 'expo-router';
import { Colors } from '@/constants/Colors';

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown:        false,
        tabBarStyle:        {
          backgroundColor: Colors.surface,
          borderTopColor:  Colors.border,
          borderTopWidth:  1,
          height:          60,
          paddingBottom:   8,
        },
        tabBarActiveTintColor:   Colors.green,
        tabBarInactiveTintColor: Colors.textMuted,
        tabBarLabelStyle:        { fontSize: 11, fontWeight: '500' },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{ title: 'Dashboard', tabBarIcon: ({ color }) => <TabIcon label="⬡" color={color} /> }}
      />
      <Tabs.Screen
        name="breaches"
        options={{ title: 'Breaches', tabBarIcon: ({ color }) => <TabIcon label="⚑" color={color} /> }}
      />
      <Tabs.Screen
        name="insights"
        options={{ title: 'Insights', tabBarIcon: ({ color }) => <TabIcon label="◎" color={color} /> }}
      />
      <Tabs.Screen
        name="memory"
        options={{ title: 'Memory', tabBarIcon: ({ color }) => <TabIcon label="◈" color={color} /> }}
      />
      <Tabs.Screen
        name="ai"
        options={{ title: 'AI', tabBarIcon: ({ color }) => <TabIcon label="⬡" color={color} /> }}
      />
      <Tabs.Screen
        name="chat"
        options={{ title: 'Chat', tabBarIcon: ({ color }) => <TabIcon label="◌" color={color} /> }}
      />
      <Tabs.Screen
        name="settings"
        options={{ title: 'Settings', tabBarIcon: ({ color }) => <TabIcon label="⚙" color={color} /> }}
      />
    </Tabs>
  );
}

function TabIcon({ label, color }: { label: string; color: string }) {
  const { Text } = require('react-native');
  return <Text style={{ fontSize: 18, color }}>{label}</Text>;
}
