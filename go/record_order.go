package cassetter

import "sort"

func orderedRecordings[T any](values []T, orders []uint64) []T {
	indices := make([]int, len(values))
	for index := range indices {
		indices[index] = index
	}
	sort.SliceStable(indices, func(left int, right int) bool {
		return orders[indices[left]] < orders[indices[right]]
	})
	ordered := make([]T, 0, len(values))
	for _, index := range indices {
		ordered = append(ordered, values[index])
	}
	return ordered
}
