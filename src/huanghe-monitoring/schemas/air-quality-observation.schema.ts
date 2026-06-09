import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import { HydratedDocument } from 'mongoose';

export type AirQualityObservationDocument =
  HydratedDocument<AirQualityObservation>;

@Schema({
  collection: 'air_quality_observations',
  timestamps: false,
})
export class AirQualityObservation {
  @Prop({
    required: true,
  })
  stationCode!: string;

  @Prop({
    type: Date,
    required: true,
  })
  datetime!: Date;

  @Prop()
  date!: string;

  @Prop()
  hour!: number;

  @Prop()
  aqi!: number;

  @Prop()
  pm25!: number;

  @Prop()
  pm25_24h!: number;

  @Prop()
  pm10!: number;

  @Prop()
  pm10_24h!: number;

  @Prop()
  so2!: number;

  @Prop()
  so2_24h!: number;

  @Prop()
  no2!: number;

  @Prop()
  no2_24h!: number;

  @Prop()
  o3!: number;

  @Prop()
  o3_24h!: number;

  @Prop()
  o3_8h!: number;

  @Prop()
  o3_8h_24h!: number;

  @Prop()
  co!: number;

  @Prop()
  co_24h!: number;
}

export const AirQualityObservationSchema = SchemaFactory.createForClass(
  AirQualityObservation,
);
