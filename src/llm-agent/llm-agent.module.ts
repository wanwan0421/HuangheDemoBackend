import { Module } from '@nestjs/common';
import { LlmAgentService } from './llm-agent.service';
import { LlmAgentController } from './llm-agent.controller';
import { MongooseModule } from '@nestjs/mongoose';
import { ModelResource, ModelResourceSchema } from 'src/resource/schemas/modelResource.schema';

@Module({
  imports: [MongooseModule.forFeature([
    {name: ModelResource.name, schema: ModelResourceSchema}
  ])],
  providers: [LlmAgentService],
  controllers: [LlmAgentController]
})
export class LlmAgentModule {}
