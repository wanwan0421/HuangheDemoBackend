import { Module } from '@nestjs/common';
import { MongooseModule } from '@nestjs/mongoose';
import { DataMappingController } from './data-mapping.controller';
import { DataMappingService } from './data-mapping.service';
import { DataScanResult, DataScanResultSchema } from './schemas/data-scan-result.schema';

@Module({
  imports: [
    MongooseModule.forFeature([
      { name: DataScanResult.name, schema: DataScanResultSchema },
    ]),
  ],
  controllers: [DataMappingController],
  providers: [DataMappingService]
})
export class DataMappingModule {}
