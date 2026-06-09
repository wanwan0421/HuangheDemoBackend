import { Module } from '@nestjs/common';
import { MongooseModule } from '@nestjs/mongoose';
import { HuangheMonitoringController } from './huanghe-monitoring.controller';
import { HuangheMonitoringService } from './huanghe-monitoring.service';

import {
  AirQualityStation,
  AirQualityStationSchema,
} from './schemas/air-quality-station.schema';
import {
  AirQualityObservation,
  AirQualityObservationSchema,
} from './schemas/air-quality-observation.schema';
@Module({
  imports: [
    MongooseModule.forFeature([
      {
        name: AirQualityStation.name,
        schema: AirQualityStationSchema,
      },
      {
        name: AirQualityObservation.name,
        schema: AirQualityObservationSchema,
      },
    ]),
  ],
  controllers: [HuangheMonitoringController], //注册之后接口生效
  providers: [HuangheMonitoringService],
})
export class HuangheMonitoringModule {}
