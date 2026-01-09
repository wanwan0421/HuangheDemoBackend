import { Module } from '@nestjs/common';
import { DataMappingController } from './data-mapping.controller';
import { DataMappingService } from './data-mapping.service';

@Module({
  controllers: [DataMappingController],
  providers: [DataMappingService]
})
export class DataMappingModule {}
