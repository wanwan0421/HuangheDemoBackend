import { Module } from '@nestjs/common';
import { HttpModule } from '@nestjs/axios';
import { ResourceService } from './resource.service';
import { ModelUtilsService } from './modelUtils.service';
import { ResourceController } from './resource.controller';
import { MongooseModule } from '@nestjs/mongoose';
import { ModelResource, ModelResourceSchema } from './schemas/modelResource.schema';

@Module({
  imports: [
    HttpModule,
    MongooseModule.forFeature([{ name: ModelResource.name, schema: ModelResourceSchema }])
  ],
  providers: [ResourceService, ModelUtilsService],
  controllers: [ResourceController],
  exports: [ResourceService],
})
export class ResourceModule {}
