import {
  Injectable,
  NotFoundException,
  BadRequestException,
} from '@nestjs/common';
import { InjectModel } from '@nestjs/mongoose';
import { Model } from 'mongoose';

import {
  AirQualityStation,
  AirQualityStationDocument,
} from './schemas/air-quality-station.schema';
import {
  AirQualityObservation,
  AirQualityObservationDocument,
} from './schemas/air-quality-observation.schema';

@Injectable()
export class HuangheMonitoringService {
  constructor(
    @InjectModel(AirQualityStation.name) //把已经注册好的MongoDB模型注入到Service里，我要在这个service里使用那一张数据库表
    private readonly airQualityStationModel: Model<AirQualityStationDocument>,

    @InjectModel(AirQualityObservation.name)
    private readonly airQualityObservationModel: Model<AirQualityObservationDocument>, //MOdel是mongoose提供的数据库模型类型，能让我调用一些查询方法
  ) {}

  /**
   * 查询黄河流域内全部空气质量监测站点
   */
  async getAllStations() {
    return this.airQualityStationModel
      .find(
        {}, //查询条件，这里是空对象，表示查询所有记录
        {
          _id: 0,
          stationCode: 1,
          stationName: 1,
          city: 1,
          longitude: 1,
          latitude: 1,
          controlPoint: 1,
          location: 1,
        }, //指定返回哪些字段，不返回哪些字段
      )
      .sort({ city: 1, stationCode: 1 })
      .lean() //查询结果直接返回普通javascript对象，而不是mongoose文档对象
      .exec(); //执行查询，返回一个Promise对象，查询完成后会得到查询结果
  }
  /**
   *根据站点编码查询单个站点详情
   */
  async getStationByCode(stationCode: string) {
    const station = await this.airQualityStationModel
      .findOne(
        { stationCode },
        {
          _id: 0,
          stationCode: 1,
          stationName: 1,
          city: 1,
          longitude: 1,
          latitude: 1,
          controlPoint: 1,
          location: 1,
        },
      )
      .lean()
      .exec();

    if (!station) {
      throw new NotFoundException(`站点 ${stationCode} 不存在`);
    }

    return station;
  }

  /**
   * 根据站点编码查询该站点的空气质量监测时间序列数据
   */
  /**
   * 根据站点编码查询空气质量监测数据
   * 支持按日期范围筛选
   */
  async getStationObservations(
    stationCode: string,
    startDate?: string,
    endDate?: string,
  ) {
    const query: Record<string, any> = {
      stationCode,
    };

    /**
     * 规则：
     * 1. startDate 和 endDate 要么都不传，要么都传
     * 2. 格式必须是 YYYY-MM-DD
     * 3. 开始日期不能晚于结束日期
     */
    if ((startDate && !endDate) || (!startDate && endDate)) {
      throw new BadRequestException('startDate 和 endDate 必须同时传入');
    }

    if (startDate && endDate) {
      const datePattern = /^\d{4}-\d{2}-\d{2}$/;

      if (!datePattern.test(startDate) || !datePattern.test(endDate)) {
        throw new BadRequestException('日期格式错误，应为 YYYY-MM-DD');
      }

      const start = new Date(`${startDate}T00:00:00.000Z`);
      const end = new Date(`${endDate}T23:59:59.999Z`);

      if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
        throw new BadRequestException('日期无效');
      }

      if (start > end) {
        throw new BadRequestException('开始日期不能晚于结束日期');
      }

      query.datetime = {
        $gte: start,
        $lte: end,
      };
    }

    const observations = await this.airQualityObservationModel
      .find(query, {
        _id: 0,
        stationCode: 1,
        datetime: 1,
        date: 1,
        hour: 1,
        aqi: 1,
        pm25: 1,
        pm25_24h: 1,
        pm10: 1,
        pm10_24h: 1,
        so2: 1,
        so2_24h: 1,
        no2: 1,
        no2_24h: 1,
        o3: 1,
        o3_24h: 1,
        o3_8h: 1,
        o3_8h_24h: 1,
        co: 1,
        co_24h: 1,
      })
      .sort({ datetime: 1 })
      .lean()
      .exec();

    return observations;
  }
}
