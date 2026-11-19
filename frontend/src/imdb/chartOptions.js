const COLORS = {
  red: '#e35d72',
  purple: '#a56bd8',
  green: '#6fe0a8',
  blue: '#70a5eb',
  amber: '#e7b86e',
  text: '#a79fae',
  line: 'rgba(255, 255, 255, 0.08)'
}

const countFormatter = (value) => Number(value ?? 0).toLocaleString('zh-CN')

function baseOption() {
  return {
    animationDuration: 450,
    backgroundColor: 'transparent',
    textStyle: { color: COLORS.text, fontFamily: 'Segoe UI, Microsoft YaHei, sans-serif' },
    tooltip: {
      trigger: 'axis',
      confine: true,
      backgroundColor: 'rgba(20, 17, 24, 0.96)',
      borderColor: 'rgba(255, 255, 255, 0.12)',
      textStyle: { color: '#e8e3ee' }
    },
    legend: {
      top: 8,
      textStyle: { color: COLORS.text }
    },
    grid: { left: 64, right: 28, top: 58, bottom: 48, containLabel: true }
  }
}

function categoryAxis(data, extra = {}) {
  return {
    type: 'category',
    data,
    axisLine: { lineStyle: { color: COLORS.line } },
    axisTick: { show: false },
    axisLabel: { color: COLORS.text },
    ...extra
  }
}

function valueAxis(name, extra = {}) {
  return {
    type: 'value',
    name,
    nameTextStyle: { color: COLORS.text },
    min: 0,
    axisLabel: { color: COLORS.text, formatter: (value) => countFormatter(value), hideOverlap: true },
    splitLine: { lineStyle: { color: COLORS.line } },
    ...extra
  }
}

export function makeDecadeOption(data = []) {
  return {
    ...baseOption(),
    tooltip: { ...baseOption().tooltip, valueFormatter: countFormatter },
    xAxis: categoryAxis(data.map((entry) => entry.decade)),
    yAxis: valueAxis('电影数'),
    series: [
      {
        name: '电影总量',
        type: 'bar',
        data: data.map((entry) => entry.total),
        itemStyle: { color: COLORS.purple, borderRadius: [4, 4, 0, 0] },
        barMaxWidth: 32
      },
      {
        name: '已有 IMDb 评分',
        type: 'bar',
        data: data.map((entry) => entry.rated),
        itemStyle: { color: COLORS.red, borderRadius: [4, 4, 0, 0] },
        barMaxWidth: 32
      }
    ]
  }
}

export function makeGenreOption(data = []) {
  const option = baseOption()
  return {
    ...option,
    grid: { ...option.grid, left: 104, right: 38, top: 52, bottom: 56 },
    tooltip: { ...option.tooltip, valueFormatter: countFormatter },
    xAxis: valueAxis('计入次数', {
      nameLocation: 'middle',
      nameGap: 30
    }),
    yAxis: categoryAxis(data.map((entry) => entry.genre), { inverse: true }),
    series: [
      {
        name: '类型计入次数',
        type: 'bar',
        data: data.map((entry) => entry.count),
        itemStyle: { color: COLORS.purple, borderRadius: [0, 4, 4, 0] },
        barMaxWidth: 18
      }
    ]
  }
}

export function makeRatingOption(data = []) {
  const option = baseOption()
  return {
    ...option,
    tooltip: { ...option.tooltip, valueFormatter: countFormatter },
    xAxis: categoryAxis(data.map((entry) => entry.bucket), {
      name: 'IMDb 评分区间',
      nameLocation: 'middle',
      nameGap: 34,
      axisLabel: { color: COLORS.text, rotate: 38 }
    }),
    yAxis: valueAxis('电影数'),
    series: [
      {
        name: '有效评分电影数',
        type: 'bar',
        data: data.map((entry) => entry.count),
        itemStyle: { color: COLORS.red, borderRadius: [4, 4, 0, 0] },
        barMaxWidth: 34
      }
    ]
  }
}

export function makeVotesOption(data = []) {
  const option = baseOption()
  return {
    ...option,
    grid: { ...option.grid, left: 76 },
    tooltip: { ...option.tooltip, valueFormatter: countFormatter },
    xAxis: categoryAxis(data.map((entry) => entry.bucket), {
      name: '投票数区间',
      nameLocation: 'middle',
      nameGap: 34,
      axisLabel: { color: COLORS.text, rotate: 25 }
    }),
    yAxis: valueAxis('电影数'),
    series: [
      {
        name: '电影数',
        type: 'bar',
        data: data.map((entry) => entry.count),
        itemStyle: { color: COLORS.blue, borderRadius: [4, 4, 0, 0] },
        barMaxWidth: 44
      }
    ]
  }
}

export function makeTrendOption(data = []) {
  const option = baseOption()
  return {
    ...option,
    grid: { ...option.grid, right: 76, bottom: 72, top: 76 },
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: 0,
        start: 0,
        end: 100,
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
        moveOnMouseWheel: false
      },
      {
        type: 'slider',
        xAxisIndex: 0,
        start: 0,
        end: 100,
        height: 18,
        bottom: 10,
        borderColor: COLORS.line,
        backgroundColor: 'rgba(255, 255, 255, 0.03)',
        fillerColor: 'rgba(165, 107, 216, 0.18)',
        textStyle: { color: COLORS.text }
      }
    ],
    xAxis: categoryAxis(data.map((entry) => entry.year)),
    yAxis: [
      valueAxis('平均评分', {
        min: 0,
        max: 10,
        nameGap: 12,
        axisLabel: { color: COLORS.text }
      }),
      valueAxis('有效样本数', { splitLine: { show: false }, nameGap: 36 })
    ],
    series: [
      {
        name: '平均评分',
        type: 'line',
        yAxisIndex: 0,
        data: data.map((entry) => entry.ratingMean),
        connectNulls: false,
        showSymbol: false,
        lineStyle: { color: COLORS.red, width: 2 },
        itemStyle: { color: COLORS.red }
      },
      {
        name: '有效评分样本数',
        type: 'bar',
        yAxisIndex: 1,
        data: data.map((entry) => entry.validRatingCount),
        itemStyle: { color: 'rgba(112, 165, 235, 0.28)', borderRadius: [2, 2, 0, 0] },
        barMaxWidth: 16,
        tooltip: { valueFormatter: countFormatter }
      }
    ]
  }
}
