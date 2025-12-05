import { Module } from '@nestjs/common';
import { HttpModule } from '@nestjs/axios';
import { ResourceService } from './resource.service';
import { ResourceController } from './resource.controller';

@Module({
  imports: [HttpModule],
  providers: [ResourceService],
  controllers: [ResourceController],

  exports: [ResourceService],
})
export class ResourceModule {}
