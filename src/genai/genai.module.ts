import { Module } from '@nestjs/common';
import { GenaiController } from './genai.controller';
import { GenAIService } from './genai.service';
import { MilvusService } from './milvus.service';

@Module({
  controllers: [GenaiController],
  providers: [GenAIService, MilvusService],
  exports: [GenAIService, MilvusService]
})
export class GenAIModule {}
