import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { statusMessage } from '../../core/bot-messages';
import { IncidentsGateway } from '../../core/incidents-gateway';
import { I18nService, TranslatePipe } from '../../core/i18n';
import { STATUS } from '../../core/labels';
import { localizeTitle } from '../../core/localize';
import { Incident, StatusCode } from '../../core/models';
import { Icon } from '../../shared/icon';
import { StatusPill } from '../../shared/status-pill';

export interface StatusChangeRequest {
  readonly to: StatusCode;
  readonly comment: string;
  readonly reason?: string;
  readonly dependency?: string;
}

/** Reasons shown in the UI language; the value is es-MX because it reaches neighbors on WhatsApp. */
const NOT_APPLICABLE_REASONS = [
  { key: 'dialog.reason.private', value: 'Propiedad privada' },
  { key: 'dialog.reason.duplicate', value: 'Duplicado de otro incidente' },
  { key: 'dialog.reason.notMunicipal', value: 'No es competencia municipal' },
  { key: 'dialog.reason.notFound', value: 'No se pudo ubicar' },
];

/**
 * Confirms a status change and previews exactly what neighbors will receive,
 * so the consequence of the click is visible before it happens.
 */
@Component({
  selector: 'fy-status-dialog',
  imports: [Icon, StatusPill, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './status-dialog.html',
  styleUrl: './status-dialog.css',
})
export class StatusDialog {
  readonly incident = input.required<Incident>();
  readonly target = input<StatusCode | null>(null);
  readonly confirmed = output<StatusChangeRequest>();
  readonly closed = output<void>();

  private readonly gateway = inject(IncidentsGateway);
  private readonly i18n = inject(I18nService);
  private readonly dialog = viewChild.required<ElementRef<HTMLDialogElement>>('dialog');

  protected readonly reasons = NOT_APPLICABLE_REASONS;
  protected readonly comment = signal('');
  protected readonly reason = signal('');
  protected readonly dependency = signal('');
  protected readonly agencies = computed(() => this.gateway.agencies().filter((a) => a.mailbox));
  protected readonly status = STATUS;

  protected readonly needsReason = computed(() => this.target() === 'not_applicable');
  protected readonly needsDependency = computed(() => this.target() === 'sent_to_agency');
  protected readonly canConfirm = computed(
    () =>
      (!this.needsReason() || this.reason() !== '') &&
      (!this.needsDependency() || this.dependency() !== ''),
  );
  protected readonly actionLabel = computed(() => {
    const target = this.target();
    return target ? this.i18n.t(`action.${target}.button`) : '';
  });
  protected readonly title = computed(() => localizeTitle(this.incident().title, this.i18n));
  protected readonly agencyName = computed(
    () => this.incident().agencyName ?? this.gateway.agencyName(this.incident().agencyId),
  );
  protected readonly preview = computed(() => {
    const target = this.target();
    if (!target) return null;
    return statusMessage(
      this.incident(),
      target,
      this.agencyName(),
      new Date().toISOString(),
      this.reason() || undefined,
    );
  });

  constructor() {
    effect(() => {
      const el = this.dialog().nativeElement;
      if (this.target()) {
        this.comment.set('');
        this.reason.set('');
        this.dependency.set('');
        if (!el.open) el.showModal();
      } else if (el.open) {
        el.close();
      }
    });
  }

  protected submit(event: Event): void {
    event.preventDefault();
    const target = this.target();
    if (!target || !this.canConfirm()) return;
    this.confirmed.emit({
      to: target,
      comment: this.comment(),
      reason: this.reason() || undefined,
      dependency: this.needsDependency() ? this.dependency() : undefined,
    });
  }

  protected onTextInput(field: 'comment' | 'reason' | 'dependency', event: Event): void {
    const value = (event.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement)
      .value;
    ({ comment: this.comment, reason: this.reason, dependency: this.dependency })[field].set(value);
  }
}
