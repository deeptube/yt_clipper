import { ChartOptions, ChartFontOptions, ChartConfiguration } from 'chart.js';
import {
  medgrey,
  lightgrey,
  grey,
  sortX,
  roundX,
  roundY,
  getInputUpdater,
} from './chartutil';

export const scatterChartDefaults: ChartOptions & ChartFontOptions = {
  defaultColor: 'rgba(255, 255, 255, 1)',
  defaultFontSize: 16,
  defaultFontStyle: 'bold',
  defaultFontColor: lightgrey(1),
  maintainAspectRatio: false,
  hover: { mode: 'nearest' },
  animation: { duration: 0 },
};

const scatterPointRawSecondsFormatter = (point) => {
  return `T:${point.x.toFixed(2)}\nS:${+point.y.toFixed(2)}`;
};

// const scatterPointHHMMSSFormatter = (point) => {
//   return `T:${+toHHMMSSTrimmed(point.x)}\nS:${+point.y.toFixed(2)}`;
// };

export function getScatterPointColor(context) {
  var index = context.dataIndex;
  var value = context.dataset.data[index];
  return value.y <= 1
    ? `rgba(255, ${100 * value.y}, 100, 0.9)`
    : `rgba(${130 - 90 * (value.y - 1)}, 100, 245, 0.9)`;
}

function getScatterChartBounds(chartInstance) {
  const scatterChartBounds = {
    XMinBound: chartInstance.options.scales.xAxes[0].ticks.min,
    XMaxBound: chartInstance.options.scales.xAxes[0].ticks.max,
    YMinBound: 0.05,
    YMaxBound: 2,
  };
  return scatterChartBounds;
}

const display = function(context) {
  return context.active ? true : 'auto';
};
const align = function(context) {
  const index = context.dataIndex;
  // const value = context.dataset.data[index];
  if (index === 0) {
    return 'right';
  } else if (index === context.dataset.data.length - 1) {
    return 'left';
  } else if (context.dataset.data[context.dataIndex].y > 1.85) {
    return 'start';
  } else {
    return 'end';
  }
};

const onHover = (event, chartElement) => {
  event.target.style.cursor = chartElement[0] ? 'grab' : 'default';
};

export function scatterChartSpec(inputId): ChartConfiguration {
  const updateInput = getInputUpdater(inputId);

  const onDragStart = function(e, chartInstance, element) {
    // console.log(e, element);
    chartInstance.options.plugins.zoom.pan.enabled = false;
    event.target.style.cursor = 'grabbing';
    chartInstance.update();
  };

  const onDrag = function(e, chartInstance, datasetIndex, index, fromValue, toValue) {
    // console.log(datasetIndex, index, fromValue, toValue);
    const shouldDrag = {
      dragX: true,
      dragY: true,
    };
    const scatterChartBounds = getScatterChartBounds(chartInstance);
    if (
      fromValue.x <= scatterChartBounds.XMinBound ||
      fromValue.x >= scatterChartBounds.XMaxBound ||
      toValue.x <= scatterChartBounds.XMinBound ||
      toValue.x >= scatterChartBounds.XMaxBound
    ) {
      shouldDrag.dragX = false;
    }
    if (
      toValue.y < scatterChartBounds.YMinBound ||
      toValue.y > scatterChartBounds.YMaxBound
    ) {
      shouldDrag.dragY = false;
    }

    return shouldDrag;
  };
  const onDragEnd = function(e, chartInstance, datasetIndex, index, value) {
    // console.log(datasetIndex, index, value);
    if (index === 0) {
      updateInput(value.y);
    } else {
      updateInput();
    }
    chartInstance.data.datasets[datasetIndex].data.sort(sortX);
    chartInstance.options.plugins.zoom.pan.enabled = true;
    event.target.style.cursor = 'default';
    chartInstance.update({ duration: 0 });
  };

  const onClick = function(event, dataAtClick) {
    if (
      event.button === 0 &&
      !event.ctrlKey &&
      !event.altKey &&
      event.shiftKey &&
      dataAtClick.length === 0
    ) {
      // console.log(element, dataAtClick);

      let valueX, valueY;
      valueX = this.scales['x-axis-1'].getValueForPixel(event.offsetX);
      valueY = this.scales['y-axis-1'].getValueForPixel(event.offsetY);

      if (valueX && valueY) {
        const scatterChartBounds = getScatterChartBounds(this);
        if (
          valueX <= scatterChartBounds.XMinBound ||
          valueX >= scatterChartBounds.XMaxBound ||
          valueY < scatterChartBounds.YMinBound ||
          valueY > scatterChartBounds.YMaxBound
        ) {
          return;
        }
        valueX = roundX(valueX);
        valueY = roundY(valueY);

        this.data.datasets[0].data.push({
          x: valueX,
          y: valueY,
        });

        this.data.datasets[0].data.sort(sortX);
        updateInput();
        this.update();
      }
    }

    if (
      event.button === 0 &&
      !event.ctrlKey &&
      event.altKey &&
      event.shiftKey &&
      dataAtClick.length === 1
    ) {
      const datum = dataAtClick[0];
      if (datum) {
        const datasetIndex = datum['_datasetIndex'];
        const index = datum['_index'];
        let scatterChartMinBound = this.options.scales.xAxes[0].ticks.min;
        let scatterChartMaxBound = this.options.scales.xAxes[0].ticks.max;
        let dataRef = this.data.datasets[datasetIndex].data;
        if (
          dataRef[index].x !== scatterChartMinBound &&
          dataRef[index].x !== scatterChartMaxBound
        ) {
          dataRef.splice(index, 1);
          updateInput();
          this.update();
        }
      }
    }

    if (event.ctrlKey && !event.altKey && !event.shiftKey) {
      this.resetZoom();
    }
  };
  return {
    type: 'scatter',
    options: {
      elements: {
        line: {
          fill: true,
          backgroundColor: 'rgba(160,0, 255, 0.1)',
          borderColor: lightgrey(0.8),
          borderWidth: 2,
          borderDash: [5, 2],
        },
      },
      legend: { display: false },
      layout: {
        padding: {
          left: 0,
          right: 0,
          top: 15,
          bottom: 0,
        },
      },
      tooltips: { enabled: false },
      scales: {
        xAxes: [
          {
            scaleLabel: {
              display: true,
              labelString: 'Time (s)',
              fontSize: 12,
              padding: 0,
            },
            position: 'bottom',
            gridLines: {
              color: medgrey(0.6),
              lineWidth: 1,
            },
            ticks: {
              min: 0,
              max: 10,
              maxTicksLimit: 100,
              autoSkip: false,
              maxRotation: 60,
              minRotation: 0,
              major: { fontColor: 'red' },
              minor: {},
            },
          },
        ],
      },

      plugins: {
        datalabels: {
          clip: false,
          clamp: true,
          font: {
            size: 14,
            weight: 'bold',
          },
          textStrokeWidth: 2,
          textStrokeColor: grey(0.9),
          textAlign: 'center',
          formatter: scatterPointRawSecondsFormatter,
          display: display,
          align: align,
          color: getScatterPointColor,
        },
        zoom: {
          pan: {
            enabled: true,
            mode: 'x',
            rangeMin: {
              x: 0,
              y: 0,
            },
            rangeMax: {
              x: 10,
              y: 2,
            },
          },
          zoom: {
            enabled: true,
            mode: 'x',
            drag: false,
            speed: 0.1,
            rangeMin: {
              x: 0,
              y: 0,
            },
            rangeMax: {
              x: 10,
              y: 2,
            },
          },
        },
      },
      annotation: {
        drawTime: 'afterDraw',
        annotations: [
          {
            label: 'time',
            type: 'line',
            mode: 'vertical',
            scaleID: 'x-axis-1',
            value: 2,
            borderColor: 'rgba(255, 0, 0, 0.9)',
            borderWidth: 1,
          },
          {
            label: 'start',
            type: 'line',
            display: true,
            mode: 'vertical',
            scaleID: 'x-axis-1',
            value: -1,
            borderColor: 'rgba(0, 255, 0, 0.9)',
            borderWidth: 1,
          },
          {
            label: 'end',
            type: 'line',
            display: true,
            mode: 'vertical',
            scaleID: 'x-axis-1',
            value: -1,
            borderColor: 'rgba(255, 215, 0, 0.9)',
            borderWidth: 1,
          },
        ],
      },
      onHover: onHover,
      dragData: true,
      dragY: true,
      dragX: true,
      dragDataRound: 0.5,
      dragDataRoundMultipleX: 0.05,
      dragDataRoundPrecisionX: 2,
      dragDataRoundMultipleY: 0.05,
      dragDataRoundPrecisionY: 2,
      dragDataSort: false,
      dragDataSortFunction: sortX,
      onDragStart: onDragStart,
      onDrag: onDrag,
      onDragEnd: onDragEnd,
      onClick: onClick,
    },
  };
}
