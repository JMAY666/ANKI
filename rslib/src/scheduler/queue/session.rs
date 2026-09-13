// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! Reservations isolate presentation while the existing scheduler owns every
//! answer.

use anki_proto::scheduler::ReviewCardAnswer;
use anki_proto::scheduler::ReviewCardRequest;
use anki_proto::scheduler::ReviewCardResponse;

use super::CardQueues;
use super::QueuedCards;
use crate::notes::Note;
use crate::prelude::*;

#[derive(Debug)]
pub(crate) struct ReviewSession {
    deck_id: DeckId,
    card: Card,
    note: Note,
    queues: CardQueues,
    queued: QueuedCards,
    token: u64,
    pub(crate) invalidated: bool,
}

impl ReviewSession {
    fn response(&self) -> ReviewCardResponse {
        ReviewCardResponse {
            queued_cards: Some(self.queued.clone().into()),
            token: self.token,
            stale: false,
        }
    }
}

impl Collection {
    fn review_session_valid(&mut self, id: &str) -> Result<bool> {
        let today = self.timing_today()?.days_elapsed;
        let Some(session) = self.state.review_sessions.get(id) else {
            return Ok(false);
        };
        Ok(!session.invalidated
            && self.storage.get_deck(session.deck_id)?.is_some()
            && session.queues.current_day == today
            && self.storage.get_card(session.card.id)?.as_ref() == Some(&session.card)
            && self.storage.get_note(session.note.id)?.as_ref() == Some(&session.note))
    }

    pub(crate) fn review_session_card(
        &mut self,
        input: ReviewCardRequest,
    ) -> Result<ReviewCardResponse> {
        require!(
            !input.session_id.is_empty() && input.session_id.len() <= 128,
            "invalid review session"
        );
        let deck_id = DeckId(input.deck_id);
        if input.validate_only {
            return if self.review_session_valid(&input.session_id)? {
                let session = &self.state.review_sessions[&input.session_id];
                let deck_id = session.deck_id;
                let card = session.card.clone();
                let mut response = session.response();
                let mut reserved = Vec::new();
                for id in self
                    .state
                    .review_sessions
                    .keys()
                    .cloned()
                    .collect::<Vec<_>>()
                {
                    if self.review_session_valid(&id)? {
                        reserved.push(self.state.review_sessions[&id].card.clone());
                    }
                }
                let counts = self
                    .build_queues_with_reservations(deck_id, &reserved)?
                    .counts();
                let queued = response.queued_cards.as_mut().unwrap();
                queued.new_count = counts.new as u32;
                queued.review_count = counts.review as u32;
                queued.learning_count = counts.learning as u32;
                match card.queue {
                    crate::card::CardQueue::New => queued.new_count += 1,
                    crate::card::CardQueue::Review => queued.review_count += 1,
                    _ => queued.learning_count += 1,
                }
                Ok(response)
            } else {
                Ok(ReviewCardResponse {
                    stale: true,
                    ..Default::default()
                })
            };
        }
        // At most two panes per collection; bound memory even for invalid callers.
        require!(
            self.state.review_sessions.len() < 2
                || self.state.review_sessions.contains_key(&input.session_id),
            "review session limit reached"
        );
        self.state.review_sessions.remove(&input.session_id);
        let mut reserved = Vec::new();
        for id in self
            .state
            .review_sessions
            .keys()
            .cloned()
            .collect::<Vec<_>>()
        {
            if self.review_session_valid(&id)? {
                reserved.push(self.state.review_sessions[&id].card.clone());
            }
        }
        let mut queues = self.build_queues_with_reservations(deck_id, &reserved)?;
        if input.keep_card_id != 0 {
            let id = CardId(input.keep_card_id);
            if let Some(position) = queues.main.iter().position(|entry| entry.id == id) {
                let entry = queues.main.remove(position).unwrap();
                queues.main.push_front(entry);
            } else if !queues.iter().any(|entry| entry.card_id() == id) {
                self.clear_study_queues();
                return Ok(ReviewCardResponse {
                    stale: true,
                    ..Default::default()
                });
            }
        }
        // The queued-card API and state computation continue to use native queues.
        // This swap is confined to one backend call, never a UI-global deck change.
        self.state.card_queues = Some(queues);
        let result = (|| -> Result<QueuedCards> {
            let mut queued = self.get_queued_cards(1, false)?;
            if input.keep_card_id != 0
                && queued.cards.first().map(|card| card.card.id.0) != Some(input.keep_card_id)
            {
                // A newly due intraday card may precede the held main card. The held
                // card remains eligible; obtain its native states without answering it.
                let card = self
                    .storage
                    .get_card(CardId(input.keep_card_id))?
                    .or_not_found(input.keep_card_id)?;
                let states = self.get_scheduling_states(card.id)?;
                let context = super::new_scheduling_context(self, &card)?;
                let kind = super::QueueEntry::from(&card).kind();
                queued.cards = vec![super::QueuedCard {
                    card,
                    states,
                    context,
                    kind,
                }];
            }
            Ok(queued)
        })();
        let queues = self.state.card_queues.take();
        let queued = result?;
        let Some(first) = queued.cards.first() else {
            return Ok(ReviewCardResponse {
                queued_cards: Some(queued.into()),
                ..Default::default()
            });
        };
        let card = first.card.clone();
        let note = self
            .storage
            .get_note(card.note_id)?
            .or_not_found(card.note_id)?;
        self.state.review_token += 1;
        let session = ReviewSession {
            deck_id,
            card,
            note,
            queues: queues.unwrap(),
            queued,
            token: self.state.review_token,
            invalidated: false,
        };
        let response = session.response();
        self.state.review_sessions.insert(input.session_id, session);
        Ok(response)
    }

    pub(crate) fn answer_review_session(
        &mut self,
        input: ReviewCardAnswer,
    ) -> Result<OpOutput<()>> {
        require!(
            self.review_session_valid(&input.session_id)?,
            "review card is stale; refresh before answering"
        );
        let supplied = input.answer.or_invalid("missing review answer")?;
        let session = &self.state.review_sessions[&input.session_id];
        require!(
            session.token == input.token && session.card.id.0 == supplied.card_id,
            "review answer already submitted or obsolete"
        );
        // Use the exact queue that issued this card. Native answer validation,
        // FSRS, limits, sibling burial, revlog and undo all run in one transaction.
        let mut session = self
            .state
            .review_sessions
            .remove(&input.session_id)
            .unwrap();
        self.state.card_queues = Some(session.queues);
        let result = self.answer_card(&mut supplied.into());
        if let Some(queues) = self.state.card_queues.take() {
            session.queues = queues;
            if result.is_err() {
                self.state.review_sessions.insert(input.session_id, session);
            }
        }
        result
    }
}

#[cfg(test)]
mod tests {
    use anki_proto::scheduler::card_answer::Rating;
    use anki_proto::scheduler::CardAnswer;

    use super::*;
    use crate::tests::DeckAdder;
    use crate::tests::NoteAdder;

    fn take(col: &mut Collection, side: &str, deck: DeckId) -> ReviewCardResponse {
        col.review_session_card(ReviewCardRequest {
            session_id: side.into(),
            deck_id: deck.0,
            ..Default::default()
        })
        .unwrap()
    }

    fn answer(response: &ReviewCardResponse, side: &str) -> ReviewCardAnswer {
        let card = &response.queued_cards.as_ref().unwrap().cards[0];
        let states = card.states.clone().unwrap();
        ReviewCardAnswer {
            session_id: side.into(),
            token: response.token,
            answer: Some(CardAnswer {
                card_id: card.card.as_ref().unwrap().id,
                current_state: states.current,
                new_state: states.good,
                rating: Rating::Good as i32,
                answered_at_millis: TimestampMillis::now().0,
                milliseconds_taken: 1234,
            }),
        }
    }

    #[test]
    fn review_session_right_can_answer_before_left_without_changing_left() {
        let mut col = Collection::new();
        NoteAdder::basic(&mut col).add(&mut col);
        NoteAdder::basic(&mut col).add(&mut col);
        let left = take(&mut col, "left", DeckId(1));
        let right = take(&mut col, "right", DeckId(1));
        let left_answer = answer(&left, "left");
        let right_answer = answer(&right, "right");
        let id = CardId(left_answer.answer.as_ref().unwrap().card_id);
        let before = col.storage.get_card(id).unwrap();
        assert_ne!(id.0, right_answer.answer.as_ref().unwrap().card_id);
        col.answer_review_session(right_answer.clone()).unwrap();
        assert_eq!(col.storage.get_card(id).unwrap(), before);
        assert!(col.review_session_valid("left").unwrap());
        assert!(col.answer_review_session(right_answer).is_err());
        col.answer_review_session(left_answer).unwrap();
        let count: i64 = col
            .storage
            .db
            .query_row("select count(*) from revlog", [], |r| r.get(0))
            .unwrap();
        assert_eq!(count, 2);
        col.undo().unwrap();
        assert_eq!(col.storage.get_card(id).unwrap(), before);
    }

    #[test]
    fn review_session_reservations_share_the_daily_limit_and_release_it() {
        let mut col = Collection::new();
        col.update_default_deck_config(|config| config.new_per_day = 1);
        NoteAdder::basic(&mut col).add(&mut col);
        NoteAdder::basic(&mut col).add(&mut col);
        let left = take(&mut col, "left", DeckId(1));
        assert_eq!(left.queued_cards.unwrap().cards.len(), 1);
        assert!(take(&mut col, "right", DeckId(1))
            .queued_cards
            .unwrap()
            .cards
            .is_empty());
        col.state.review_sessions.remove("left");
        assert_eq!(
            take(&mut col, "right", DeckId(1))
                .queued_cards
                .unwrap()
                .cards
                .len(),
            1
        );
    }

    #[test]
    fn review_session_parent_and_child_never_issue_the_same_card() {
        let mut col = Collection::new();
        let parent = DeckAdder::new("Parent").add(&mut col);
        let child = DeckAdder::new("Parent::Child").add(&mut col);
        NoteAdder::basic(&mut col).deck(child.id).add(&mut col);
        NoteAdder::basic(&mut col).deck(child.id).add(&mut col);
        let left = take(&mut col, "left", parent.id);
        let right = take(&mut col, "right", child.id);
        assert_ne!(
            answer(&left, "left").answer.unwrap().card_id,
            answer(&right, "right").answer.unwrap().card_id
        );
        assert_eq!(col.get_current_deck().unwrap().id, DeckId(1));
    }

    #[test]
    fn review_session_sibling_burial_applies_across_panes() {
        let mut col = Collection::new();
        col.update_default_deck_config(|config| config.bury_new = true);
        NoteAdder::new(&col.basic_rev_notetype())
            .fields(&["front", "back"])
            .add(&mut col);
        assert_eq!(
            take(&mut col, "left", DeckId(1))
                .queued_cards
                .unwrap()
                .cards
                .len(),
            1
        );
        assert!(take(&mut col, "right", DeckId(1))
            .queued_cards
            .unwrap()
            .cards
            .is_empty());
    }

    #[test]
    fn review_session_rejects_edited_card_without_creating_a_review() {
        let mut col = Collection::new();
        NoteAdder::basic(&mut col).add(&mut col);
        let left = take(&mut col, "left", DeckId(1));
        let request = answer(&left, "left");
        col.storage
            .db
            .execute("update notes set flds = 'changed'", [])
            .unwrap();
        assert!(col.answer_review_session(request).is_err());
        let count: i64 = col
            .storage
            .db
            .query_row("select count(*) from revlog", [], |r| r.get(0))
            .unwrap();
        assert_eq!(count, 0);
    }

    #[test]
    fn review_session_respects_common_parent_limits_for_separate_children() {
        let mut col = Collection::new();
        col.set_config_bool(BoolKey::ApplyAllParentLimits, true, true)
            .unwrap();
        DeckAdder::new("Parent")
            .with_config(|config| config.inner.new_per_day = 1)
            .add(&mut col);
        let a = DeckAdder::new("Parent::A").add(&mut col);
        let b = DeckAdder::new("Parent::B").add(&mut col);
        NoteAdder::basic(&mut col).deck(a.id).add(&mut col);
        NoteAdder::basic(&mut col).deck(b.id).add(&mut col);
        assert_eq!(
            take(&mut col, "left", a.id)
                .queued_cards
                .unwrap()
                .cards
                .len(),
            1
        );
        assert!(take(&mut col, "right", b.id)
            .queued_cards
            .unwrap()
            .cards
            .is_empty());
    }

    #[test]
    fn review_session_uses_native_scheduling_and_rejects_a_replaced_token() {
        let mut col = Collection::new();
        NoteAdder::basic(&mut col).add(&mut col);
        let native: anki_proto::scheduler::QueuedCards =
            col.get_queued_cards(1, false).unwrap().into();
        let first = take(&mut col, "left", DeckId(1));
        assert_eq!(
            first.queued_cards.as_ref().unwrap().cards[0].states,
            native.cards[0].states
        );
        let obsolete = answer(&first, "left");
        let second = take(&mut col, "left", DeckId(1));
        assert!(col.answer_review_session(obsolete).is_err());
        col.answer_review_session(answer(&second, "left")).unwrap();
    }

    #[test]
    fn review_session_failed_answer_rolls_back_card_and_revlog() {
        let mut col = Collection::new();
        NoteAdder::basic(&mut col).add(&mut col);
        let response = take(&mut col, "left", DeckId(1));
        let mut request = answer(&response, "left");
        let id = CardId(request.answer.as_ref().unwrap().card_id);
        let before = col.storage.get_card(id).unwrap();
        let supplied = request.answer.as_mut().unwrap();
        supplied.current_state = supplied.new_state.clone();
        assert!(col.answer_review_session(request).is_err());
        assert_eq!(col.storage.get_card(id).unwrap(), before);
        let count: i64 = col
            .storage
            .db
            .query_row("select count(*) from revlog", [], |r| r.get(0))
            .unwrap();
        assert_eq!(count, 0);
    }

    #[test]
    fn review_session_new_reservation_also_reserves_shared_review_budget() {
        let mut col = Collection::new();
        col.set_config_bool(BoolKey::ApplyAllParentLimits, true, true)
            .unwrap();
        col.set_config_bool(BoolKey::NewCardsIgnoreReviewLimit, false, true)
            .unwrap();
        DeckAdder::new("Parent")
            .with_config(|config| config.inner.reviews_per_day = 1)
            .add(&mut col);
        let new_deck = DeckAdder::new("Parent::New").add(&mut col);
        let review_deck = DeckAdder::new("Parent::Reviews").add(&mut col);
        NoteAdder::basic(&mut col).deck(new_deck.id).add(&mut col);
        crate::tests::CardAdder::new()
            .deck(review_deck.id)
            .due_dates(["0"])
            .add(&mut col);
        assert_eq!(
            take(&mut col, "left", new_deck.id)
                .queued_cards
                .unwrap()
                .cards
                .len(),
            1
        );
        assert!(take(&mut col, "right", review_deck.id)
            .queued_cards
            .unwrap()
            .cards
            .is_empty());
    }

    #[test]
    fn review_session_keeps_non_rescheduling_filtered_deck_semantics() {
        let mut col = Collection::new();
        let note = NoteAdder::basic(&mut col).add(&mut col);
        let id = col.storage.card_ids_of_notes(&[note.id]).unwrap()[0];
        let original = col.storage.get_card(id).unwrap().unwrap();
        let mut filtered = Deck::new_filtered();
        filtered.filtered_mut().unwrap().reschedule = false;
        col.add_or_update_deck(&mut filtered).unwrap();
        col.rebuild_filtered_deck(filtered.id).unwrap();
        let response = take(&mut col, "left", filtered.id);
        col.answer_review_session(answer(&response, "left"))
            .unwrap();
        let restored = col.storage.get_card(id).unwrap().unwrap();
        assert_eq!(restored.deck_id, original.deck_id);
        assert_eq!(restored.due, original.due);
        assert_eq!(restored.interval, original.interval);
        assert_eq!(restored.queue, original.queue);
    }
}
