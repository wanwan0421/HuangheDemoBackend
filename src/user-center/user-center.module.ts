import { Module } from '@nestjs/common';
import { MongooseModule } from '@nestjs/mongoose';
import { UserCenterController } from './user-center.controller';
import { UserCenterService } from './user-center.service';
import { UserCenter, UserCenterSchema } from './schemas/user-center.schema';

@Module({
  imports: [
    MongooseModule.forFeature([{ name: UserCenter.name, schema: UserCenterSchema }]),
  ],
  controllers: [UserCenterController],
  providers: [UserCenterService],
  exports: [UserCenterService],
})
export class UserCenterModule {}
