import { Controller, Get, Param, Query } from '@nestjs/common';
import { HuangheMonitoringService } from './huanghe-monitoring.service';

@Controller('huanghe-monitoring')
export class HuangheMonitoringController {
  constructor(
    private readonly huangheMonitoringService: HuangheMonitoringService,
  ) {}

  /**
   * 获取黄河流域内所有空气质量监测站点
   * GET /huanghe-monitoring/stations
   */
  @Get('stations')
  async getAllStations() {
    return this.huangheMonitoringService.getAllStations();
  }

  // 根据站点编码获取单个站点详情
  @Get('stations/:stationCode')
  async getStationByCode(@Param('stationCode') stationCode: string) {
    return this.huangheMonitoringService.getStationByCode(stationCode);
  }

  /**
   * 获取某站点在指定时间范围内的空气质量监测数据
   * GET /huanghe-monitoring/stations/:stationCode/observations
   * ?startDate=2020-05-08&endDate=2020-05-14
   */
  @Get('stations/:stationCode/observations')
  async getStationObservations(
    @Param('stationCode') stationCode: string,
    @Query('startDate') startDate?: string,
    @Query('endDate') endDate?: string,
  ) {
    return this.huangheMonitoringService.getStationObservations(
      stationCode,
      startDate,
      endDate,
    );
  }
}
