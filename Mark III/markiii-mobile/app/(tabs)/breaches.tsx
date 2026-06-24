import React from 'react';
import { View, Text, FlatList, StyleSheet, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Colors } from '@/constants/Colors';
import { useBreaches } from '@/hooks/useServerStatus';
import { BreachCard } from '@/components/BreachCard';
import type { BreachRecord } from '@/services/api';

export default function BreachesScreen() {
  const { data: breaches, isLoading, isError, refetch } = useBreaches();

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.header}>
        <Text style={styles.title}>Breach Log</Text>
        <Text style={styles.sub}>Rabbit-hole threshold crossings</Text>
      </View>

      {isLoading && (
        <View style={styles.center}>
          <ActivityIndicator color={Colors.green} />
        </View>
      )}

      {isError && (
        <View style={styles.center}>
          <Text style={styles.errorText}>Could not load breaches.</Text>
          <Text style={styles.errorSub}>Check brain server connection.</Text>
        </View>
      )}

      {breaches && breaches.length === 0 && (
        <View style={styles.center}>
          <Text style={styles.emptyText}>No breaches recorded.</Text>
          <Text style={styles.emptySub}>
            Browse YouTube for 15 minutes and check back.{'\n'}(Not a challenge.)
          </Text>
        </View>
      )}

      {breaches && breaches.length > 0 && (
        <FlatList<BreachRecord>
          data={breaches}
          keyExtractor={(item) => String(item.id)}
          renderItem={({ item }) => <BreachCard breach={item} />}
          contentContainerStyle={styles.list}
          onRefresh={refetch}
          refreshing={isLoading}
          showsVerticalScrollIndicator={false}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:      { flex: 1, backgroundColor: Colors.bg },
  header:    { padding: 20, paddingBottom: 12 },
  title:     { fontSize: 28, fontWeight: '700', color: Colors.textPrimary },
  sub:       { fontSize: 13, color: Colors.textMuted, marginTop: 2 },
  list:      { paddingHorizontal: 20, paddingBottom: 40 },
  center:    { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  errorText: { fontSize: 16, color: Colors.red, fontWeight: '600', textAlign: 'center' },
  errorSub:  { fontSize: 13, color: Colors.textMuted, marginTop: 8, textAlign: 'center' },
  emptyText: { fontSize: 16, color: Colors.textSecondary, fontWeight: '500', textAlign: 'center' },
  emptySub:  { fontSize: 13, color: Colors.textMuted, marginTop: 8, textAlign: 'center', lineHeight: 19 },
});
