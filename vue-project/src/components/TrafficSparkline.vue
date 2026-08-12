<script setup lang="ts">
import { computed } from 'vue'
import type { TrafficHistoryPoint } from '../bridge/pythonApi'

const props = defineProps<{
  points: TrafficHistoryPoint[]
}>()

const chartPoints = computed<TrafficHistoryPoint[]>(() => {
  const points = props.points?.slice(-40) ?? []
  if (points.length >= 2) {
    return points
  }

  if (points.length === 1) {
    const first = points[0]!
    return [
      {
        ...first,
        timestamp: first.timestamp - 1,
      },
      first,
    ]
  }

  return Array.from({ length: 12 }, (_, index) => ({
    timestamp: index,
    time: '',
    uploadBytesPerSecond: 0,
    downloadBytesPerSecond: 0,
  }))
})

type TrafficMetric = 'uploadBytesPerSecond' | 'downloadBytesPerSecond'

type TrafficLane = {
  metric: TrafficMetric
  top: number
  bottom: number
}

const uploadLane: TrafficLane = {
  metric: 'uploadBytesPerSecond',
  top: 5,
  bottom: 23,
}

const downloadLane: TrafficLane = {
  metric: 'downloadBytesPerSecond',
  top: 29,
  bottom: 47,
}

function getLaneMaxRate(metric: TrafficMetric) {
  return Math.max(1, ...chartPoints.value.map((point) => point[metric]))
}

function buildPath(lane: TrafficLane) {
  const width = 120
  const padding = 5
  const points = chartPoints.value
  const lastIndex = Math.max(1, points.length - 1)
  const laneHeight = lane.bottom - lane.top
  const maxRate = getLaneMaxRate(lane.metric)

  return points
    .map((point, index) => {
      const x = padding + (index / lastIndex) * (width - padding * 2)
      const ratio = Math.min(1, Math.max(0, point[lane.metric] / maxRate))
      const y = lane.bottom - ratio * laneHeight

      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`
    })
    .join(' ')
}

const uploadPath = computed(() => buildPath(uploadLane))
const downloadPath = computed(() => buildPath(downloadLane))
</script>

<template>
  <svg class="traffic-sparkline" viewBox="0 0 120 52" aria-hidden="true" focusable="false">
    <path class="traffic-baseline upload-baseline" d="M5 23 L115 23" />
    <path class="traffic-baseline download-baseline" d="M5 47 L115 47" />
    <path class="traffic-line upload" :d="uploadPath" />
    <path class="traffic-line download" :d="downloadPath" />
  </svg>
</template>

<style scoped>
.traffic-sparkline {
  display: block;
  overflow: visible;
}

.traffic-baseline {
  fill: none;
  stroke: rgba(116, 137, 168, 0.22);
  stroke-width: 1.5;
  stroke-linecap: round;
}

.traffic-baseline.upload-baseline {
  stroke: rgba(31, 143, 105, 0.2);
}

.traffic-baseline.download-baseline {
  stroke: rgba(45, 117, 214, 0.2);
}

.traffic-line {
  fill: none;
  stroke-width: 3.4;
  stroke-linecap: round;
  stroke-linejoin: round;
  vector-effect: non-scaling-stroke;
}

.traffic-line.upload {
  stroke: var(--green);
}

.traffic-line.download {
  stroke: var(--blue);
}
</style>
