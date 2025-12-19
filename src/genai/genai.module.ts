import { Module } from '@nestjs/common';
import { GenaiController } from './genai.controller';
import { GenAIService } from './genai.service';

@Module({
  controllers: [GenaiController],
  providers: [GenAIService],
  exports: [GenAIService]
})
export class GenAIModule {}
