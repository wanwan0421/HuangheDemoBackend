import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import { HydratedDocument } from 'mongoose';

export type AirQualityStationDocument = HydratedDocument<AirQualityStation>;

@Schema({
  collection: 'air_quality_stations',
  timestamps: false,
})
export class AirQualityStation {
  @Prop({
    required: true,
  })
  stationCode!: string;

  @Prop()
  stationName!: string;

  @Prop()
  city!: string;

  @Prop()
  longitude!: number;

  @Prop()
  latitude!: number;

  @Prop()
  controlPoint!: string;

  @Prop({
    type: {
      type: String,
      enum: ['Point'],
      default: 'Point',
    },
    coordinates: {
      type: [Number],
      default: [],
    },
  })
  location!: {
    type: 'Point';
    coordinates: [number, number];
  };
}

export const AirQualityStationSchema =
  SchemaFactory.createForClass(AirQualityStation);
