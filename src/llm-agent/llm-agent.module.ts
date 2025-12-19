import { Module } from '@nestjs/common';
import { LlmAgentService } from './llm-agent.service';
import { LlmAgentController } from './llm-agent.controller';
import { MongooseModule } from '@nestjs/mongoose';
import { ModelResource, ModelResourceSchema } from 'src/resource/schemas/modelResource.schema';
import { IndexModule } from 'src/index/index.module';
import { ResourceModule } from 'src/resource/resource.module';
import { GenAIModule } from 'src/genai/genai.module';

@Module({
  imports: [
  MongooseModule.forFeature([{name: ModelResource.name, schema: ModelResourceSchema}]),
  IndexModule, ResourceModule, GenAIModule],
  providers: [LlmAgentService],
  controllers: [LlmAgentController]
})
export class LlmAgentModule {}
