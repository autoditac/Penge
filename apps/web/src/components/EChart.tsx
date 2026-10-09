/** Thin typed React wrapper around a tree-shaken ECharts core (ADR-0036).
 *
 * Registers only the chart/component modules the app uses and renders with
 * the SVG renderer (crisp at dashboard sizes, no canvas dependency in tests).
 */

import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import {
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import type { ComposeOption } from "echarts/core";
import type { ECElementEvent } from "echarts/core";
import type { BarSeriesOption, LineSeriesOption, PieSeriesOption } from "echarts/charts";
import type {
  AxisPointerComponentOption,
  DataZoomComponentOption,
  GridComponentOption,
  LegendComponentOption,
  TooltipComponentOption,
} from "echarts/components";

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  SVGRenderer,
]);

export type EChartOption = ComposeOption<
  | BarSeriesOption
  | LineSeriesOption
  | PieSeriesOption
  | AxisPointerComponentOption
  | DataZoomComponentOption
  | GridComponentOption
  | LegendComponentOption
  | TooltipComponentOption
>;

type EChartProps = {
  readonly option: EChartOption;
  readonly height: number;
  readonly ariaLabel: string;
  readonly onDataPointClick?: ((dataIndex: number) => void) | undefined;
};

export function EChart({
  option,
  height,
  ariaLabel,
  onDataPointClick,
}: EChartProps): React.JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (container === null) {
      return;
    }
    const chart = echarts.init(container, null, { renderer: "svg" });
    chartRef.current = chart;
    const observer = new ResizeObserver(() => {
      chart.resize();
    });
    observer.observe(container);
    return () => {
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, { notMerge: true });
  }, [option]);

  useEffect(() => {
    const chart = chartRef.current;
    if (chart === null || onDataPointClick === undefined) {
      return;
    }
    const handleClick = (event: ECElementEvent): void => {
      if (event.componentType === "series" && typeof event.dataIndex === "number") {
        onDataPointClick(event.dataIndex);
      }
    };
    chart.on("click", handleClick);
    return () => {
      chart.off("click", handleClick);
    };
  }, [onDataPointClick]);

  return <div ref={containerRef} role="img" aria-label={ariaLabel} style={{ height }} />;
}
