import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  effect,
  inject,
  input,
  signal,
  viewChild,
} from '@angular/core';
import { FOLLOW_UP_REPLIES } from '../../core/bot-messages';
import { formatClockEs } from '../../core/format';
import { hasDemoControls, IncidentsGateway } from '../../core/incidents-gateway';
import { DEMO_CITIZEN } from '../../core/scenario';
import { BrandMark } from '../../shared/brand-mark';
import { Icon } from '../../shared/icon';

/**
 * The demo citizen's WhatsApp, rebuilt from the messages the notifier sent.
 * Lets the judges see both sides of the loop on one screen.
 */
@Component({
  selector: 'fy-phone-mirror',
  imports: [BrandMark, Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './phone-mirror.html',
  styleUrl: './phone-mirror.css',
})
export class PhoneMirror {
  readonly compact = input(false);

  private readonly gateway = inject(IncidentsGateway);
  private readonly chat = viewChild<ElementRef<HTMLElement>>('chat');

  protected readonly citizen = DEMO_CITIZEN;
  protected readonly replies = FOLLOW_UP_REPLIES;
  protected readonly simulated = this.gateway.simulated;
  protected readonly showEnglish = signal(true);
  protected readonly canReply = hasDemoControls(this.gateway);

  protected readonly thread = computed(() =>
    this.gateway.messages().filter((m) => m.to === this.citizen),
  );

  constructor() {
    effect(() => {
      this.thread();
      const el = this.chat()?.nativeElement;
      if (el) queueMicrotask(() => el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' }));
    });
  }

  protected clock(iso: string): string {
    return formatClockEs(iso);
  }

  protected reply(incidentId: string, fixed: boolean): void {
    if (hasDemoControls(this.gateway)) this.gateway.replyToFollowUp(incidentId, fixed);
  }
}
