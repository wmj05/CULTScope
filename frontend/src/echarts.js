
// CULTScope 3.5.5B: shared ECharts 5 registrations.
import * as echarts from 'echarts/core'

import {
    BarChart,
    LineChart,
    ScatterChart
} from 'echarts/charts'

import {
    GridComponent,
    TooltipComponent,
    LegendComponent,
    DataZoomComponent
} from 'echarts/components'

import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
    BarChart,
    LineChart,
    ScatterChart,
    GridComponent,
    TooltipComponent,
    LegendComponent,
    DataZoomComponent,
    CanvasRenderer
])

export { echarts }